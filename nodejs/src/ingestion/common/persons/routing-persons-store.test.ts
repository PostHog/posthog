import { personhogStoreShadowErrorsCounter, personhogStoreShadowSkipsCounter } from '~/common/persons/metrics'
import { InternalPerson } from '~/types'

import { RoutingPersonsStore, assertPersonsStoreModeConfig, parsePersonsStoreMode } from './routing-persons-store'

jest.mock('~/common/persons/metrics', () => ({
    personhogStoreShadowErrorsCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
    personhogStoreShadowSkipsCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
}))

describe('RoutingPersonsStore', () => {
    const person = (teamId: number): InternalPerson =>
        ({ id: '1', team_id: teamId, properties: {}, is_identified: false }) as unknown as InternalPerson

    const ops = { set: {}, setOnce: {}, unset: [], denied: false, shouldForceUpdate: false, eventName: '$set' }

    const makeStores = () => {
        const pg = {
            fetchForChecking: jest.fn().mockResolvedValue(null),
            fetchForUpdate: jest.fn().mockResolvedValue(person(1)),
            applyEventOps: jest.fn().mockResolvedValue([person(1), []]),
            createPerson: jest.fn().mockResolvedValue({ success: true }),
            deletePerson: jest.fn().mockResolvedValue([]),
            moveDistinctIds: jest.fn().mockResolvedValue({ success: true }),
            prefetchPersons: jest.fn().mockResolvedValue(undefined),
            flush: jest.fn().mockResolvedValue([]),
            releaseBatch: jest.fn(),
            shutdown: jest.fn().mockResolvedValue(undefined),
        } as any
        const personhog = {
            fetchForChecking: jest.fn().mockResolvedValue(null),
            fetchForUpdate: jest.fn().mockResolvedValue(person(1)),
            applyEventOps: jest.fn().mockResolvedValue([person(1), []]),
            createPerson: jest.fn().mockResolvedValue({ success: true }),
            deletePerson: jest.fn().mockResolvedValue([]),
            prefetchPersons: jest.fn().mockResolvedValue(undefined),
            flush: jest.fn().mockResolvedValue([]),
            releaseBatch: jest.fn(),
            removeDistinctIdFromCache: jest.fn(),
            shutdown: jest.fn().mockResolvedValue(undefined),
        } as any
        return { pg, personhog }
    }

    it('rejects an unknown mode at parse time', () => {
        expect(() => parsePersonsStoreMode('both')).toThrow('PERSONS_STORE_MODE')
        expect(parsePersonsStoreMode('shadow')).toBe('shadow')
    })

    it.each([
        ['shadow', '', 'id:1', 'PERSONHOG_ADDR'],
        ['personhog', 'router:1', '', 'PERSONHOG_IDENTITY_ADDR'],
        ['shadow', '', '', 'PERSONHOG_ADDR and PERSONHOG_IDENTITY_ADDR'],
    ] as const)('%s mode without endpoints fails at boot naming the knob', (mode, routerAddr, identityAddr, named) => {
        expect(() => assertPersonsStoreModeConfig(mode, { routerAddr, identityAddr })).toThrow(named)
    })

    it('pg mode needs no endpoints', () => {
        expect(() => assertPersonsStoreModeConfig('pg', { routerAddr: '', identityAddr: '' })).not.toThrow()
    })

    describe('personhog mode with a team allowlist', () => {
        it('routes allowlisted teams to personhog and the rest to pg', async () => {
            const { pg, personhog } = makeStores()
            const store = new RoutingPersonsStore(pg, personhog, 'personhog', new Set([1]))

            await store.fetchForUpdate(1, 'a', 0)
            expect(personhog.fetchForUpdate).toHaveBeenCalledWith(1, 'a', 0)
            expect(pg.fetchForUpdate).not.toHaveBeenCalled()

            await store.fetchForUpdate(2, 'b', 0)
            expect(pg.fetchForUpdate).toHaveBeenCalledWith(2, 'b', 0)
        })

        it('a personhog flush failure propagates, because the store is authoritative', async () => {
            const { pg, personhog } = makeStores()
            personhog.flush.mockRejectedValue(new Error('leader down'))
            const store = new RoutingPersonsStore(pg, personhog, 'personhog', null)
            store.forBatch(7)
            await expect(store.flush()).rejects.toThrow('leader down')
        })
    })

    describe('shadow mode', () => {
        it('returns the pg result and runs the personhog verb after it', async () => {
            const { pg, personhog } = makeStores()
            const pgPerson = person(1)
            pg.applyEventOps.mockResolvedValue([pgPerson, []])
            const store = new RoutingPersonsStore(pg, personhog, 'shadow', null)

            const [updated] = await store.applyEventOps(person(1), ops as any, 'a', 0)
            expect(updated).toBe(pgPerson)
            expect(personhog.applyEventOps).toHaveBeenCalled()
        })

        it('a personhog failure is counted and never fails the batch', async () => {
            const { pg, personhog } = makeStores()
            personhog.applyEventOps.mockRejectedValue(new Error('identity down'))
            const store = new RoutingPersonsStore(pg, personhog, 'shadow', null)

            await expect(store.applyEventOps(person(1), ops as any, 'a', 0)).resolves.toBeDefined()
            expect(personhogStoreShadowErrorsCounter.labels).toHaveBeenCalledWith({ verb: 'applyEventOps' })
        })

        it('a pg failure still fails the batch', async () => {
            const { pg, personhog } = makeStores()
            pg.applyEventOps.mockRejectedValue(new Error('pg down'))
            const store = new RoutingPersonsStore(pg, personhog, 'shadow', null)
            await expect(store.applyEventOps(person(1), ops as any, 'a', 0)).rejects.toThrow('pg down')
            expect(personhog.applyEventOps).not.toHaveBeenCalled()
        })

        it('a personhog flush failure is swallowed', async () => {
            const { pg, personhog } = makeStores()
            personhog.flush.mockRejectedValue(new Error('leader down'))
            const store = new RoutingPersonsStore(pg, personhog, 'shadow', null)
            store.forBatch(7)
            await expect(store.flush()).resolves.toEqual([])
            expect(personhog.flush).toHaveBeenCalledWith(7)
        })
    })

    describe('verbs that never route', () => {
        it('merge execution stays on pg for an allowlisted team', async () => {
            const { pg, personhog } = makeStores()
            const store = new RoutingPersonsStore(pg, personhog, 'personhog', new Set([1]))
            const tx = {} as any
            await store.moveDistinctIds(person(1), person(1), 'a', undefined, tx, 0)
            expect(pg.moveDistinctIds).toHaveBeenCalled()
        })

        it('a transactional create stays on pg for an allowlisted team', async () => {
            const { pg, personhog } = makeStores()
            const store = new RoutingPersonsStore(pg, personhog, 'personhog', new Set([1]))
            const tx = {} as any
            await store.createPerson(
                null as any,
                {},
                {},
                {},
                1,
                null,
                false,
                'uuid',
                { distinctId: 'a' },
                undefined,
                tx,
                0
            )
            expect(pg.createPerson).toHaveBeenCalled()
            expect(personhog.createPerson).not.toHaveBeenCalled()
        })
    })

    it('prefetch splits entries by route', async () => {
        const { pg, personhog } = makeStores()
        const store = new RoutingPersonsStore(pg, personhog, 'personhog', new Set([1]))
        await store.prefetchPersons([
            { teamId: 1, distinctId: 'a', batchId: 0 },
            { teamId: 2, distinctId: 'b', batchId: 0 },
        ])
        expect(pg.prefetchPersons).toHaveBeenCalledWith([{ teamId: 2, distinctId: 'b', batchId: 0 }])
        expect(personhog.prefetchPersons).toHaveBeenCalledWith([{ teamId: 1, distinctId: 'a', batchId: 0 }])
    })

    it('a released batch is no longer flushed on the personhog side', async () => {
        const { pg, personhog } = makeStores()
        const store = new RoutingPersonsStore(pg, personhog, 'shadow', null)
        store.forBatch(7)
        store.releaseBatch(7)
        await store.flush()
        expect(personhog.flush).not.toHaveBeenCalled()
        expect(personhog.releaseBatch).toHaveBeenCalledWith(7)
    })

    describe('shadow writes resolve the personhog world person', () => {
        const pgPerson = { id: '7', team_id: 1, properties: {} } as unknown as InternalPerson
        const shadowPerson = { id: '99', team_id: 1, properties: {} } as unknown as InternalPerson

        it.each([
            [
                'applyEventOps',
                (store: RoutingPersonsStore) => store.applyEventOps(pgPerson, ops as any, 'd1', 0),
                (personhog: any) => personhog.applyEventOps,
            ],
            [
                'updatePersonWithPropertiesDiffForUpdate',
                (store: RoutingPersonsStore) =>
                    store.updatePersonWithPropertiesDiffForUpdate(pgPerson, { a: '1' }, [], {}, 'd1', 0),
                (personhog: any) => personhog.updatePersonWithPropertiesDiffForUpdate,
            ],
        ] as const)('%s ships the shadow world id, not the pg id', async (_verb, call, personhogFn) => {
            const { pg, personhog } = makeStores()
            personhog.fetchForUpdate.mockResolvedValue(shadowPerson)
            personhog.updatePersonWithPropertiesDiffForUpdate = jest.fn().mockResolvedValue([shadowPerson, [], true])
            pg.updatePersonWithPropertiesDiffForUpdate = jest.fn().mockResolvedValue([pgPerson, [], true])
            const store = new RoutingPersonsStore(pg, personhog, 'shadow', null)

            await call(store)

            // The pg call keeps the caller's person; the shadowed call must
            // re-resolve, because pg ids mean nothing in the personhog world.
            const shadowArgs = personhogFn(personhog).mock.calls[0]
            expect(shadowArgs[0].id).toBe('99')
        })

        it('skips the shadow write, counted, when the person does not exist in the personhog world', async () => {
            const { pg, personhog } = makeStores()
            pg.applyEventOps.mockResolvedValue([pgPerson, []])
            personhog.fetchForUpdate.mockResolvedValue(null)
            const store = new RoutingPersonsStore(pg, personhog, 'shadow', null)

            const [result] = await store.applyEventOps(pgPerson, ops as any, 'd1', 0)

            expect(result.id).toBe('7')
            expect(personhog.applyEventOps).not.toHaveBeenCalled()
            expect(personhogStoreShadowSkipsCounter.labels).toHaveBeenCalledWith({ verb: 'applyEventOps' })
        })

        it('a failing shadow resolution is swallowed like any shadow error', async () => {
            const { pg, personhog } = makeStores()
            pg.applyEventOps.mockResolvedValue([pgPerson, []])
            personhog.fetchForUpdate.mockRejectedValue(new Error('identity down'))
            const store = new RoutingPersonsStore(pg, personhog, 'shadow', null)

            const [result] = await store.applyEventOps(pgPerson, ops as any, 'd1', 0)

            expect(result.id).toBe('7')
            expect(personhogStoreShadowErrorsCounter.labels).toHaveBeenCalledWith({ verb: 'applyEventOps' })
        })
    })

    it('shutdown closes the personhog side even when pg shutdown fails', async () => {
        const { pg, personhog } = makeStores()
        pg.shutdown.mockRejectedValue(new Error('pg teardown failed'))
        const store = new RoutingPersonsStore(pg, personhog, 'shadow', null)

        await expect(store.shutdown()).rejects.toThrow('pg teardown failed')
        expect(personhog.shutdown).toHaveBeenCalled()
    })
})
