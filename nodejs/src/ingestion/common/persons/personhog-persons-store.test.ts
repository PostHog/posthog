import { DateTime } from 'luxon'

import { PersonHogPersonWriteRepository } from '~/common/personhog/personhog-person-write-repository'
import { PersonhogPropertiesSizeError } from '~/common/personhog/persons'
import { NoRowsUpdatedError } from '~/common/utils/utils'
import { InternalPerson } from '~/types'

import { extractEventOps } from './person-update'
import { PersonhogPendingRpcError, PersonhogPersonsStore } from './personhog-persons-store'

describe('PersonhogPersonsStore', () => {
    let repository: jest.Mocked<PersonHogPersonWriteRepository>
    let store: PersonhogPersonsStore
    let person: InternalPerson

    const ops = (properties: Record<string, unknown>, event = '$set') =>
        extractEventOps({
            event,
            distinct_id: 'd1',
            properties,
            team_id: 1,
            uuid: 'event-uuid',
            ip: null,
            now: '2026-08-07T00:00:00Z',
            site_url: '',
        } as any)

    beforeEach(() => {
        person = {
            id: '7',
            uuid: 'person-uuid',
            team_id: 1,
            properties: { plan: 'free' },
            created_at: DateTime.fromMillis(3_600_000, { zone: 'utc' }),
            version: 1,
            properties_last_updated_at: {},
            properties_last_operation: {},
            is_user_id: null,
            is_identified: false,
            last_seen_at: null,
        }
        repository = {
            resolvePersonsByDistinctIds: jest.fn().mockResolvedValue([]),
            fetchPersonById: jest.fn().mockResolvedValue(null),
            // An applied write bumps the version, as the leader does.
            updatePersonProperties: jest.fn().mockResolvedValue({ person: { ...person, version: 2 }, updated: true }),
            getDistinctIdsForPersons: jest.fn().mockResolvedValue({}),
            getOrCreatePersonByDistinctId: jest.fn().mockResolvedValue({ person, created: true }),
        } as unknown as jest.Mocked<PersonHogPersonWriteRepository>
        store = new PersonhogPersonsStore(repository)
    })

    it('folds a batch of ops into one leader call per person and publishes nothing', async () => {
        const bound = store.forBatch(0)
        await bound.applyEventOps(person, ops({ $set: { a: '1' }, $set_once: { first: 'x' } }), 'd1')
        await bound.applyEventOps(person, ops({ $set: { a: '2', first: 'shadowed' } }), 'd1')
        await bound.applyEventOps(person, ops({ $unset: ['gone'] }), 'd1')

        const results = await bound.flush()

        expect(repository.updatePersonProperties).toHaveBeenCalledTimes(1)
        const sent = repository.updatePersonProperties.mock.calls[0][0]
        expect(sent.personId).toEqual('7')
        expect(sent.setProperties).toEqual({ a: '2', first: 'shadowed' })
        expect(sent.setOnceProperties).toEqual({})
        expect(sent.unsetProperties).toEqual(['gone'])
        // The changelog is this world's ClickHouse feed: a flush ships
        // segments and publishes nothing.
        expect(results).toEqual([])
    })

    it('returns a locally projected person while the leader stays authoritative at flush', async () => {
        const bound = store.forBatch(0)
        const eventOps = ops({ $set: { plan: 'pro' }, $set_once: { plan: 'ignored', fresh: 'kept' } })
        eventOps.isIdentified = true
        eventOps.lastSeenAtMs = 7_200_000

        const [projected, messages] = await bound.applyEventOps(person, eventOps, 'd1')

        expect(messages).toEqual([])
        expect(projected.properties).toEqual({ plan: 'pro', fresh: 'kept' })
        expect(projected.is_identified).toBe(true)
        expect(projected.last_seen_at?.toMillis()).toEqual(7_200_000)
        expect(person.properties).toEqual({ plan: 'free' })
    })

    describe('flush suppression of filtered-only lanes', () => {
        it('a lane of unforced filtered-only changes never reaches the leader', async () => {
            person.properties = { $browser: 'Firefox' }
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { $browser: 'Chrome' } }, 'pageview'), 'd1')
            const results = await bound.flush()
            expect(repository.updatePersonProperties).not.toHaveBeenCalled()
            expect(results).toEqual([])
        })

        it.each([
            ['a person event forces the write', { $browser: 'Firefox' }, { $set: { $browser: 'Chrome' } }, '$set'],
            ['a new key always counts', {}, { $set: { $browser: 'Chrome' } }, 'pageview'],
            ['an unset always counts', { $browser: 'Firefox' }, { $unset: ['$browser'] }, 'pageview'],
        ])('%s and the lane ships', async (_label, baseline, props, event) => {
            person.properties = { ...(baseline as Record<string, string>) }
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops(props as Record<string, unknown>, event as string), 'd1')
            await bound.flush()
            expect(repository.updatePersonProperties).toHaveBeenCalledTimes(1)
        })

        it('a scalar move ships without property changes', async () => {
            const bound = store.forBatch(0)
            const scalarOnly = ops({}, 'pageview')
            scalarOnly.isIdentified = true
            await bound.applyEventOps(person, scalarOnly, 'd1')
            await bound.flush()
            expect(repository.updatePersonProperties).toHaveBeenCalledTimes(1)
        })

        it('one update-worthy event makes the whole lane ship', async () => {
            person.properties = { $browser: 'Firefox' }
            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { $browser: 'Chrome' } }, 'pageview'), 'd1')
            await bound.applyEventOps(person, ops({ $set: { plan: 'pro' } }, 'pageview'), 'd1')
            await bound.flush()
            expect(repository.updatePersonProperties).toHaveBeenCalledTimes(1)
        })
    })

    it('does not fold denied events', async () => {
        const bound = store.forBatch(0)
        await bound.applyEventOps(person, ops({ $set: { a: '1' } }, '$exception'), 'd1')
        const results = await bound.flush()
        expect(repository.updatePersonProperties).not.toHaveBeenCalled()
        expect(results).toEqual([])
    })

    it('a denied event still ships its scalars, without its properties', async () => {
        const bound = store.forBatch(0)
        const denied = ops({ $set: { a: '1' } }, '$exception')
        denied.lastSeenAtMs = 7_200_000
        const [projected] = await bound.applyEventOps(person, denied, 'd1')
        expect(projected.last_seen_at?.toMillis()).toBe(7_200_000)
        expect(projected.properties).toEqual({ plan: 'free' })

        await bound.flush()
        const sent = repository.updatePersonProperties.mock.calls[0][0]
        expect(sent.lastSeenAtMs).toBe(7_200_000)
        expect(sent.setProperties).toEqual({})
    })

    it('memoizes update fetches per batch, resolving once and reading state once', async () => {
        repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }])
        repository.fetchPersonById.mockResolvedValue({ ...person })
        const bound = store.forBatch(0)
        await bound.fetchForUpdate(1, 'd1')
        await bound.fetchForUpdate(1, 'd1')
        expect(repository.resolvePersonsByDistinctIds).toHaveBeenCalledTimes(1)
        expect(repository.fetchPersonById).toHaveBeenCalledTimes(1)
    })

    it('update fetches take state from the leader, not the resolution', async () => {
        // The identity resolve returns writer-applied state; the leader's
        // is fresher and must win as the projection baseline.
        repository.resolvePersonsByDistinctIds.mockResolvedValue([
            { teamId: 1, distinctId: 'd1', person: { ...person, properties: { plan: 'stale' } } },
        ])
        repository.fetchPersonById.mockResolvedValue({ ...person, properties: { plan: 'fresh' }, version: 9 })
        const bound = store.forBatch(0)
        const fetched = await bound.fetchForUpdate(1, 'd1')
        expect(fetched?.properties).toEqual({ plan: 'fresh' })
        expect(fetched?.version).toBe(9)
        expect(repository.fetchPersonById).toHaveBeenCalledWith(1, '7', expect.any(String))
    })

    it('checking fetches use the resolved person without a leader call', async () => {
        repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }])
        const bound = store.forBatch(0)
        const fetched = await bound.fetchForChecking(1, 'd1')
        expect(fetched?.id).toBe('7')
        expect(repository.fetchPersonById).not.toHaveBeenCalled()
    })

    it('prefetch resolves the batch once so later fetches make no calls', async () => {
        repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }])
        repository.fetchPersonById.mockResolvedValue({ ...person })
        await store.prefetchPersons([{ teamId: 1, distinctId: 'd1', batchId: 0 }])
        const bound = store.forBatch(0)
        const fetched = await bound.fetchForUpdate(1, 'd1')
        expect(fetched?.id).toBe('7')
        expect(repository.resolvePersonsByDistinctIds).toHaveBeenCalledTimes(1)
        expect(repository.fetchPersonById).toHaveBeenCalledTimes(1)
    })

    it('a stale null result cannot downgrade a live mapping', async () => {
        repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }])
        repository.fetchPersonById.mockResolvedValue({ ...person })
        const bound = store.forBatch(0)
        const fetched = await bound.fetchForUpdate(1, 'd1')
        expect(fetched?.id).toBe('7')

        // A late prefetch response reporting absence must not erase the
        // resolved mapping.
        ;(store as any).recordFetch(1, 'd1', null, 0)
        const again = await bound.fetchForUpdate(1, 'd1')
        expect(again?.id).toBe('7')
    })

    it('prefetch dedupes repeated distinct ids before resolving', async () => {
        repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }])
        repository.fetchPersonById.mockResolvedValue({ ...person })
        await store.prefetchPersons([
            { teamId: 1, distinctId: 'd1', batchId: 0 },
            { teamId: 1, distinctId: 'd1', batchId: 0 },
            { teamId: 1, distinctId: 'd1', batchId: 0 },
        ])
        expect(repository.resolvePersonsByDistinctIds).toHaveBeenCalledTimes(1)
        expect(repository.resolvePersonsByDistinctIds.mock.calls[0][0]).toEqual([{ teamId: 1, distinctId: 'd1' }])
    })

    it('a failed prefetch falls back to first-touch resolution', async () => {
        repository.resolvePersonsByDistinctIds.mockRejectedValueOnce(new Error('identity unavailable'))
        await store.prefetchPersons([{ teamId: 1, distinctId: 'd1', batchId: 0 }])
        repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }])
        repository.fetchPersonById.mockResolvedValue({ ...person })
        const bound = store.forBatch(0)
        const fetched = await bound.fetchForUpdate(1, 'd1')
        expect(fetched?.id).toBe('7')
    })

    it('deletes have no personhog path and fail loudly', async () => {
        const bound = store.forBatch(0)
        await expect(bound.deletePerson(person, 'd1')).rejects.toThrow('no personhog RPC')
    })

    it('creation resolves through identity and memoizes every distinct id it mapped', async () => {
        const bound = store.forBatch(0)
        const result = await bound.createPerson(
            DateTime.fromMillis(3_600_000, { zone: 'utc' }),
            { initial: 'props' },
            {},
            {},
            1,
            null,
            false,
            'advisory-uuid',
            { distinctId: 'd1' },
            [{ distinctId: 'd2' }]
        )

        expect(result.success).toBe(true)
        expect(repository.getOrCreatePersonByDistinctId).toHaveBeenCalledWith(
            expect.objectContaining({
                teamId: 1,
                distinctId: 'd1',
                extraDistinctIds: ['d2'],
                setProperties: { initial: 'props' },
                createdAtMs: 3_600_000,
            }),
            expect.any(String)
        )
        await bound.fetchForUpdate(1, 'd1')
        await bound.fetchForUpdate(1, 'd2')
        expect(repository.resolvePersonsByDistinctIds).not.toHaveBeenCalled()
    })

    it.each([
        ['not_found', new NoRowsUpdatedError('gone')],
        ['size_violation', new PersonhogPropertiesSizeError('too big', 1, '7')],
    ])('skips %s at flush without failing the batch', async (_outcome, error) => {
        repository.updatePersonProperties.mockRejectedValue(error)
        const bound = store.forBatch(0)
        await bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
        const results = await bound.flush()
        expect(results).toEqual([])
    })

    it('fails the flush on unexpected errors so the batch retries whole', async () => {
        repository.updatePersonProperties.mockRejectedValue(new Error('leader unreachable'))
        const bound = store.forBatch(0)
        await bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
        await expect(bound.flush()).rejects.toThrow('leader unreachable')
    })

    describe('concurrent batches share one flush', () => {
        const personB: () => InternalPerson = () => ({ ...person, id: '8', uuid: 'person-uuid-8' })

        it("a sibling entry's failure leaves it in its lane for the next pass", async () => {
            const bound0 = store.forBatch(0)
            const bound1 = store.forBatch(1)
            await bound0.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
            await bound1.applyEventOps(personB(), ops({ $set: { b: '2' } }), 'd2')

            repository.updatePersonProperties.mockImplementation((request) =>
                request.personId === '8'
                    ? Promise.reject(new Error('leader unreachable'))
                    : Promise.resolve({ person: { ...person, version: 2 }, updated: true })
            )
            await expect(store.flush()).rejects.toThrow('leader unreachable')

            repository.updatePersonProperties.mockClear()
            repository.updatePersonProperties.mockResolvedValue({ person: { ...person, version: 2 }, updated: true })
            await store.flush()
            // Only the failed entry survives to re-ship; the succeeded
            // one was consumed by the first pass.
            expect(repository.updatePersonProperties).toHaveBeenCalledTimes(1)
            expect(repository.updatePersonProperties.mock.calls[0][0].personId).toBe('8')
        })

        it('flush passes serialize, so ops folded mid-pass ship strictly after it', async () => {
            let releaseFirst!: () => void
            const firstGate = new Promise<void>((resolve) => {
                releaseFirst = resolve
            })
            const callOrder: string[] = []
            repository.updatePersonProperties
                .mockImplementationOnce(async () => {
                    callOrder.push('first:start')
                    await firstGate
                    callOrder.push('first:end')
                    return { person: { ...person, version: 2 }, updated: true }
                })
                .mockImplementation(() => {
                    callOrder.push('second')
                    return Promise.resolve({ person: { ...person, version: 3 }, updated: true })
                })

            const bound = store.forBatch(0)
            await bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
            const firstFlush = store.flush()
            // Spin microtasks until the first pass is mid-ship, blocked
            // on the gate, so the next fold genuinely lands mid-pass.
            for (let i = 0; i < 100 && !callOrder.includes('first:start'); i++) {
                await Promise.resolve()
            }
            await bound.applyEventOps(person, ops({ $set: { a: '2' } }), 'd1')
            const secondFlush = store.flush()
            releaseFirst()
            await Promise.all([firstFlush, secondFlush])

            expect(callOrder).toEqual(['first:start', 'first:end', 'second'])
        })

        it('a no-change lane ships anyway when a sibling batch holds ops for the person', async () => {
            person.properties = { $browser: 'Firefox' }
            const bound0 = store.forBatch(0)
            const bound1 = store.forBatch(1)
            // Batch 0 folds a filtered-only no-change; batch 1 holds real
            // ops for the same person, so batch 0's verdict may be stale
            // and the leader judges it instead.
            await bound0.applyEventOps(person, ops({ $set: { $browser: 'Chrome' } }, 'pageview'), 'd1')
            await bound1.applyEventOps(person, ops({ $set: { plan: 'pro' } }, 'pageview'), 'd1')
            await store.flush()
            expect(repository.updatePersonProperties).toHaveBeenCalledTimes(2)
        })
    })

    it('publishes nothing when the leader reports no change', async () => {
        repository.updatePersonProperties.mockResolvedValue({ person, updated: false })
        const bound = store.forBatch(0)
        await bound.applyEventOps(person, ops({ $set: { plan: 'free' } }), 'd1')
        const results = await bound.flush()
        expect(results).toEqual([])
    })

    it('a later segment failing on a domain error does not undo earlier segments', async () => {
        const bound = store.forBatch(0)
        const pair = ops({ $set_once: { k: 'v' }, $unset: ['k'] })
        const cutter = ops({ $set_once: { k: 'later' } })
        await bound.applyEventOps(person, pair, 'd1')
        await bound.applyEventOps(person, cutter, 'd1')

        repository.updatePersonProperties
            .mockResolvedValueOnce({ person: { ...person, version: 2 }, updated: true })
            .mockRejectedValueOnce(new PersonhogPropertiesSizeError('too big', 1, '7'))
        const results = await bound.flush()
        // Both segments shipped — the first landed before the second's
        // domain error, and the error skips rather than fails the flush.
        expect(repository.updatePersonProperties).toHaveBeenCalledTimes(2)
        expect(results).toEqual([])
    })

    it('pending state is visible through every distinct id of the person', async () => {
        const bound = store.forBatch(0)
        await bound.createPerson(
            DateTime.fromMillis(3_600_000, { zone: 'utc' }),
            {},
            {},
            {},
            1,
            null,
            false,
            'advisory-uuid',
            { distinctId: 'd1' },
            [{ distinctId: 'd2' }]
        )
        const viaD1 = await bound.fetchForUpdate(1, 'd1')
        await bound.applyEventOps(viaD1!, ops({ $set: { a: '1' } }), 'd1')

        const viaD2 = await bound.fetchForUpdate(1, 'd2')
        expect(viaD2?.properties).toMatchObject({ a: '1' })
        expect(repository.resolvePersonsByDistinctIds).not.toHaveBeenCalled()
    })

    it('pending ops are visible to later fetches and compose across events', async () => {
        repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }])
        repository.fetchPersonById.mockResolvedValue({ ...person })
        const bound = store.forBatch(0)
        const fetched = await bound.fetchForUpdate(1, 'd1')
        await bound.applyEventOps(fetched!, ops({ $set: { a: '1' } }), 'd1')

        const refetched = await bound.fetchForUpdate(1, 'd1')
        expect(refetched?.properties).toEqual({ plan: 'free', a: '1' })
        expect(repository.resolvePersonsByDistinctIds).toHaveBeenCalledTimes(1)

        const [afterSecond] = await bound.applyEventOps(refetched!, ops({ $set: { b: '2' } }), 'd1')
        expect(afterSecond.properties).toEqual({ plan: 'free', a: '1', b: '2' })
    })

    it('releaseBatch frees the batch memo so later fetches hit the service again', async () => {
        repository.resolvePersonsByDistinctIds.mockResolvedValue([{ teamId: 1, distinctId: 'd1', person }])
        repository.fetchPersonById.mockResolvedValue({ ...person })
        const bound = store.forBatch(0)
        await bound.fetchForUpdate(1, 'd1')
        store.releaseBatch(0)
        await bound.fetchForUpdate(1, 'd1')
        expect(repository.resolvePersonsByDistinctIds).toHaveBeenCalledTimes(2)
    })

    it('releaseBatch drops an unflushed lane so nothing ships for the batch', async () => {
        const bound = store.forBatch(0)
        await bound.applyEventOps(person, ops({ $set: { a: '1' } }), 'd1')
        store.releaseBatch(0)
        const results = await bound.flush()
        expect(repository.updatePersonProperties).not.toHaveBeenCalled()
        expect(results).toEqual([])
    })

    it('has no transactions of its own; the routing store owns them', async () => {
        const bound = store.forBatch(0)
        await expect(bound.inTransaction('test', () => Promise.resolve('done'))).rejects.toThrow('no personhog RPC')
    })

    it.each([
        [
            'updatePersonForMerge',
            (b: ReturnType<PersonhogPersonsStore['forBatch']>, p: InternalPerson) =>
                b.updatePersonForMerge(p, {}, 'd1'),
        ],
        [
            'addDistinctId',
            (b: ReturnType<PersonhogPersonsStore['forBatch']>, p: InternalPerson) => b.addDistinctId(p, 'd2', 0),
        ],
        [
            'moveDistinctIds',
            (b: ReturnType<PersonhogPersonsStore['forBatch']>, p: InternalPerson) =>
                b.moveDistinctIds(p, p, 'd1', undefined, undefined as any),
        ],
        [
            'moveDistinctIdsFromPersons',
            (b: ReturnType<PersonhogPersonsStore['forBatch']>, p: InternalPerson) =>
                b.moveDistinctIdsFromPersons([p], p, 'd1', undefined as any),
        ],
    ])('%s fails loudly while the leader RPC is pending', async (_method, call) => {
        const bound = store.forBatch(0)
        await expect(call(bound, person)).rejects.toThrow(PersonhogPendingRpcError)
    })

    it('maps a direct diff update onto the folded RPC', async () => {
        const bound = store.forBatch(0)
        const [updated, messages] = await bound.updatePersonWithPropertiesDiffForUpdate(
            person,
            { plan: 'pro' },
            ['gone'],
            { is_identified: true, last_seen_at: DateTime.fromMillis(7_200_000, { zone: 'utc' }) },
            'd1'
        )
        const sent = repository.updatePersonProperties.mock.calls[0][0]
        expect(sent.setProperties).toEqual({ plan: 'pro' })
        expect(sent.unsetProperties).toEqual(['gone'])
        expect(sent.isIdentified).toBe(true)
        expect(sent.lastSeenAtMs).toBe(7_200_000)
        expect(updated).toEqual({ ...person, version: 2 })
        expect(messages).toEqual([])
    })

    it('refuses a diff update carrying fields the RPC cannot express', async () => {
        const bound = store.forBatch(0)
        await expect(
            bound.updatePersonWithPropertiesDiffForUpdate(person, {}, [], { created_at: person.created_at }, 'd1')
        ).rejects.toThrow(PersonhogPendingRpcError)
        expect(repository.updatePersonProperties).not.toHaveBeenCalled()
    })
})
