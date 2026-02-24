import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { Hub } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'

import { deleteKeysWithPrefix } from '../../cdp/_tests/redis'
import { IdempotencyService, IdempotencyState, idempotencyKey } from './idempotency.service'

const mockNow = jest.spyOn(Date, 'now')

describe('IdempotencyService', () => {
    jest.retryTimes(3)

    let now: number
    let hub: Hub
    let redis: RedisV2
    let service: IdempotencyService

    const NS = 'test'

    const advanceTime = (ms: number) => {
        now += ms
        mockNow.mockReturnValue(now)
    }

    beforeEach(async () => {
        hub = await createHub()
        now = 1720000000000
        mockNow.mockReturnValue(now)

        redis = createRedisV2PoolFromConfig({
            connection: { url: hub.REDIS_URL },
            poolMinSize: hub.REDIS_POOL_MIN_SIZE,
            poolMaxSize: hub.REDIS_POOL_MAX_SIZE,
        })
        await deleteKeysWithPrefix(redis, '@posthog-test/idempotency')
        service = new IdempotencyService(redis, { maxSize: 100 })
    })

    afterEach(async () => {
        await closeHub(hub)
        jest.clearAllMocks()
    })

    describe('idempotencyKey', () => {
        it('produces consistent hashes for the same input', () => {
            expect(idempotencyKey('a', 'b')).toBe(idempotencyKey('a', 'b'))
        })

        it('produces different hashes for different inputs', () => {
            expect(idempotencyKey('a', 'b')).not.toBe(idempotencyKey('a', 'c'))
            expect(idempotencyKey('a', 'b')).not.toBe(idempotencyKey('b', 'a'))
        })

        it('produces 32-character hex strings', () => {
            const key = idempotencyKey('some-namespace', 'some-very-long-identifier-that-could-be-anything')
            expect(key).toHaveLength(32)
            expect(key).toMatch(/^[0-9a-f]{32}$/)
        })
    })

    describe('claim', () => {
        it.each([
            {
                scenario: 'new key',
                setup: async () => {},
                expected: IdempotencyState.New,
            },
            {
                scenario: 'already-claimed key',
                setup: async () => {
                    await service.claim(NS, idempotencyKey('event-1'))
                    advanceTime(10)
                },
                expected: IdempotencyState.Existing,
            },
            {
                scenario: 'acked key',
                setup: async () => {
                    await service.claim(NS, idempotencyKey('event-1'))
                    await service.ack(NS, idempotencyKey('event-1'))
                    advanceTime(10)
                },
                expected: IdempotencyState.Acked,
            },
            {
                scenario: 'released key (re-claimable)',
                setup: async () => {
                    await service.claim(NS, idempotencyKey('event-1'))
                    await service.release(NS, idempotencyKey('event-1'))
                    advanceTime(10)
                },
                expected: IdempotencyState.New,
            },
        ])('returns $expected for $scenario', async ({ setup, expected }) => {
            await setup()
            const result = await service.claim(NS, idempotencyKey('event-1'))
            expect(result).toBe(expected)
        })
    })

    describe('bounded size', () => {
        it('evicts oldest claimed entries when exceeding maxSize', async () => {
            const smallService = new IdempotencyService(redis, { maxSize: 5 })

            for (let i = 0; i < 7; i++) {
                advanceTime(100)
                await smallService.claim(NS, idempotencyKey(`event-${i}`))
            }

            advanceTime(100)
            expect(await smallService.claim(NS, idempotencyKey('event-0'))).toBe(IdempotencyState.New)
            advanceTime(100)
            expect(await smallService.claim(NS, idempotencyKey('event-1'))).toBe(IdempotencyState.New)
            advanceTime(100)
            expect(await smallService.claim(NS, idempotencyKey('event-6'))).toBe(IdempotencyState.Existing)
        })

        it('acked entries survive eviction over claimed entries', async () => {
            const smallService = new IdempotencyService(redis, { maxSize: 5 })
            const ns = 'ack-survive'

            await smallService.claim(ns, idempotencyKey('acked-event'))
            await smallService.ack(ns, idempotencyKey('acked-event'))
            advanceTime(100)
            await smallService.claim(ns, idempotencyKey('claimed-1'))
            advanceTime(100)
            await smallService.claim(ns, idempotencyKey('claimed-2'))

            for (let i = 3; i < 7; i++) {
                advanceTime(100)
                await smallService.claim(ns, idempotencyKey(`filler-${i}`))
            }

            advanceTime(100)
            expect(await smallService.claim(ns, idempotencyKey('acked-event'))).toBe(IdempotencyState.Acked)
            advanceTime(100)
            expect(await smallService.claim(ns, idempotencyKey('claimed-1'))).toBe(IdempotencyState.New)
            advanceTime(100)
            expect(await smallService.claim(ns, idempotencyKey('claimed-2'))).toBe(IdempotencyState.New)
        })
    })

    describe('claimBatch', () => {
        it('returns correct states for a mix of new, existing, and acked keys', async () => {
            const existingKey = idempotencyKey('existing')
            const ackedKey = idempotencyKey('acked')
            const newKey = idempotencyKey('new')

            await service.claim(NS, existingKey)
            await service.claim(NS, ackedKey)
            await service.ack(NS, ackedKey)
            advanceTime(100)

            const results = await service.claimBatch([
                [NS, existingKey],
                [NS, ackedKey],
                [NS, newKey],
            ])
            expect(results).not.toBeNull()
            expect(results!.get(existingKey)).toBe(IdempotencyState.Existing)
            expect(results!.get(ackedKey)).toBe(IdempotencyState.Acked)
            expect(results!.get(newKey)).toBe(IdempotencyState.New)
        })

        it('handles entries across multiple namespaces in one call', async () => {
            const key = idempotencyKey('shared-event')

            await service.claim('ns-a', key)
            await service.ack('ns-a', key)
            advanceTime(10)

            const results = await service.claimBatch([
                ['ns-a', key],
                ['ns-b', key],
            ])
            expect(results!.get(key)).toBe(IdempotencyState.New) // ns-b wins last-write in the map
            // Verify ns-a is still acked via single call
            expect(await service.claim('ns-a', key)).toBe(IdempotencyState.Acked)
        })

        it('returns empty map for empty input', async () => {
            const results = await service.claimBatch([])
            expect(results).toEqual(new Map())
        })
    })

    describe('namespaces are isolated', () => {
        it('same key in different namespaces are independent', async () => {
            const key = idempotencyKey('shared-event')

            await service.claim('ns-a', key)
            await service.ack('ns-a', key)
            advanceTime(10)

            expect(await service.claim('ns-b', key)).toBe(IdempotencyState.New)
            expect(await service.claim('ns-a', key)).toBe(IdempotencyState.Acked)
        })
    })

    describe('ackBatch', () => {
        it('marks multiple keys as acked', async () => {
            const keys = [idempotencyKey('a'), idempotencyKey('b'), idempotencyKey('c')]
            const entries: [string, (typeof keys)[number]][] = keys.map((k) => [NS, k])
            await service.claimBatch(entries)
            await service.ackBatch(entries)
            advanceTime(100)

            const results = await service.claimBatch(entries)
            for (const key of keys) {
                expect(results!.get(key)).toBe(IdempotencyState.Acked)
            }
        })
    })

    describe('releaseBatch', () => {
        it('makes multiple keys re-claimable', async () => {
            const keys = [idempotencyKey('a'), idempotencyKey('b')]
            const entries: [string, (typeof keys)[number]][] = keys.map((k) => [NS, k])
            await service.claimBatch(entries)
            await service.releaseBatch(entries)
            advanceTime(100)

            const results = await service.claimBatch(entries)
            for (const key of keys) {
                expect(results!.get(key)).toBe(IdempotencyState.New)
            }
        })
    })

    describe('touch behavior', () => {
        it('refreshes score on existing entries to prevent eviction', async () => {
            const smallService = new IdempotencyService(redis, { maxSize: 3 })
            const ns = 'touch'

            await smallService.claim(ns, idempotencyKey('A'))
            advanceTime(100)
            await smallService.claim(ns, idempotencyKey('B'))
            advanceTime(100)
            await smallService.claim(ns, idempotencyKey('C'))
            advanceTime(100)

            // Touch A by re-claiming (returns Existing but refreshes score)
            expect(await smallService.claim(ns, idempotencyKey('A'))).toBe(IdempotencyState.Existing)
            advanceTime(100)

            // Add D — should evict B (oldest untouched), not A (recently touched)
            await smallService.claim(ns, idempotencyKey('D'))
            advanceTime(100)

            // Check all at once via batch to avoid sequential claim side effects
            const results = await smallService.claimBatch([
                [ns, idempotencyKey('A')],
                [ns, idempotencyKey('B')],
                [ns, idempotencyKey('C')],
                [ns, idempotencyKey('D')],
            ])

            expect(results!.get(idempotencyKey('A'))).toBe(IdempotencyState.Existing)
            expect(results!.get(idempotencyKey('B'))).toBe(IdempotencyState.New) // evicted
            expect(results!.get(idempotencyKey('C'))).toBe(IdempotencyState.Existing)
            expect(results!.get(idempotencyKey('D'))).toBe(IdempotencyState.Existing)
        })
    })
})
