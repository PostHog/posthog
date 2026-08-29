import { Code, ConnectError } from '@connectrpc/connect'
import { DateTime } from 'luxon'

import {
    personhogStoreShadowCompareFailedCounter,
    personhogStoreShadowComparedCounter,
    personhogStoreShadowDivergenceCounter,
    personhogStoreShadowErrorsCounter,
    personhogStoreShadowSkipsCounter,
} from '~/common/persons/metrics'
import { InternalPerson } from '~/types'

import { EventOps } from './person-update'
import { PersonhogPersonsStore } from './personhog-persons-store'
import { MergePersonsResult, PersonsBackend, PersonsStore } from './persons-store'
import { RoutingPersonsStore, assertPersonsStoreModeConfig, parsePersonsStoreMode } from './routing-persons-store'

jest.mock('~/common/persons/metrics', () => ({
    personhogStoreShadowErrorsCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
    personhogStoreShadowSkipsCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
    personhogStoreShadowDivergenceCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
    personhogStoreShadowComparedCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
    personhogStoreShadowCompareFailedCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
}))

const emptyMergeResult = (): MergePersonsResult => ({ survivor: null, results: [] })

/**
 * A complete, compile-checked PersonsStore mock: the annotation forces
 * every interface member to exist, so an interface change breaks this
 * factory at compile time instead of leaving stale mocks that only fail
 * when a newly routed method runs.
 *
 * The cover is PersonsStore only. Tests hand this to the personhog slot
 * through a cast, so a member PersonhogPersonsStore adds beyond the
 * interface is not checked here and would surface at runtime.
 */
function mockStore(backend: PersonsBackend = 'postgres'): jest.Mocked<PersonsStore> {
    return {
        backend,
        fetchForChecking: jest.fn().mockResolvedValue(null),
        fetchForUpdate: jest.fn().mockResolvedValue(null),
        createPerson: jest.fn().mockResolvedValue({ success: true }),
        applyEventOps: jest.fn(),
        updatePersonWithPropertiesDiffForUpdate: jest.fn(),
        mergePersons: jest.fn().mockResolvedValue(emptyMergeResult()),
        personPropertiesSize: jest.fn().mockResolvedValue(0),
        shutdown: jest.fn().mockResolvedValue(undefined),
        prefetchPersons: jest.fn().mockResolvedValue(undefined),
        flush: jest.fn().mockResolvedValue([]),
        releaseBatch: jest.fn(),
        getFlushStats: jest.fn().mockReturnValue({ dirtyEntryCount: 0, referencedBatchCount: 0, cacheEntryCount: 0 }),
    }
}

describe('RoutingPersonsStore', () => {
    it.each([
        // Shadow's personhog calls never reach a caller, so an error a caller
        // sees during a shadow rollout came from Postgres and must say so.
        ['personhog' as const, 'personhog'],
        ['shadow' as const, 'postgres'],
    ])('reports the authoritative backend in %s mode', (mode, expected) => {
        const store = new RoutingPersonsStore(
            mockStore('postgres'),
            mockStore('personhog') as unknown as PersonhogPersonsStore,
            mode
        )
        expect(store.backend).toBe(expected)
    })

    const person = (teamId: number, id = '1'): InternalPerson =>
        ({ id, team_id: teamId, properties: {}, is_identified: false }) as unknown as InternalPerson

    const ops: EventOps = {
        set: {},
        setOnce: {},
        unset: [],
        denied: false,
        shouldForceUpdate: false,
        eventName: '$set',
    } as unknown as EventOps

    const makeStores = () => {
        const pg = mockStore()
        // The personhog store implements PersonsStore, so the same
        // compile-checked factory serves; the cast to the concrete class
        // is the constructor's requirement, not an escape from checking.
        const personhogMock = Object.assign(mockStore(), { abandonBatch: jest.fn() })
        const personhog = personhogMock as unknown as PersonhogPersonsStore
        return { pg, personhogMock, personhog }
    }

    const makeStore = (stores: ReturnType<typeof makeStores>, mode: 'personhog' | 'shadow') =>
        new RoutingPersonsStore(stores.pg, stores.personhog, mode)

    describe('shadow divergence detection', () => {
        const divergences = (): Record<string, string>[] =>
            (personhogStoreShadowDivergenceCounter.labels as jest.Mock).mock.calls.map(([labels]) => labels)
        const counted = (): boolean =>
            (personhogStoreShadowDivergenceCounter.labels as jest.Mock).mock.results.every(
                (call) => (call.value.inc as jest.Mock).mock.calls.length > 0
            )

        it.each([
            ['a different person', { uuid: 'other-uuid' }, 'uuid'],
            ['a different identified flag', { is_identified: true }, 'is_identified'],
            ['different properties', { properties: { plan: 'pro' } }, 'properties'],
        ])('records a read answering %s', async (_case, shadowDiff, field) => {
            const stores = makeStores()
            stores.pg.fetchForUpdate.mockResolvedValue(person(1, '1'))
            stores.personhogMock.fetchForUpdate.mockResolvedValue({ ...person(1, '1'), ...shadowDiff })
            const store = makeStore(stores, 'shadow')

            await store.fetchForUpdate(1, 'd1', 0)

            // The error counter says personhog fell over. Nothing said it
            // answered a different person, which is the failure shadow mode
            // exists to find.
            expect(divergences()).toContainEqual({ verb: 'fetchForUpdate', field })
            expect(counted()).toBe(true)
        })

        it('records a read that found nobody where the authoritative one found somebody', async () => {
            const stores = makeStores()
            stores.pg.fetchForUpdate.mockResolvedValue(person(1, '1'))
            stores.personhogMock.fetchForUpdate.mockResolvedValue(null)
            const store = makeStore(stores, 'shadow')

            await store.fetchForUpdate(1, 'd1', 0)

            expect(divergences()).toContainEqual({ verb: 'fetchForUpdate', field: 'missing_shadow' })
        })

        it('records nothing when the two agree', async () => {
            const stores = makeStores()
            stores.pg.fetchForUpdate.mockResolvedValue(person(1, '1'))
            stores.personhogMock.fetchForUpdate.mockResolvedValue(person(1, '1'))
            const store = makeStore(stores, 'shadow')

            await store.fetchForUpdate(1, 'd1', 0)

            expect(divergences()).toEqual([])
            expect(personhogStoreShadowComparedCounter.labels).toHaveBeenCalledWith({ verb: 'fetchForUpdate' })
        })

        it.each([
            ['a nested object whose keys arrived in another order', { a: 1, b: 2 }, { b: 2, a: 1 }, false],
            ['an array whose order actually differs', [1, 2], [2, 1], true],
        ])('reads %s correctly', async (_case, pgValue, shadowValue, diverges) => {
            const stores = makeStores()
            stores.pg.fetchForUpdate.mockResolvedValue({ ...person(1, '1'), properties: { nested: pgValue } })
            stores.personhogMock.fetchForUpdate.mockResolvedValue({
                ...person(1, '1'),
                properties: { nested: shadowValue },
            })
            const store = makeStore(stores, 'shadow')

            await store.fetchForUpdate(1, 'd1', 0)

            // Postgres stores jsonb in its own key order while the personhog
            // side arrives in the order it was written, so comparing
            // serialised forms would call every nested object a difference
            // and bury the ones that are real. Array order is the customer's.
            expect(divergences().some((labels) => labels.field === 'properties')).toBe(diverges)
        })

        it('records a merge that picked a different survivor', async () => {
            const stores = makeStores()
            stores.pg.mergePersons.mockResolvedValue({ survivor: person(1, '1'), results: [] })
            stores.personhogMock.mergePersons.mockResolvedValue({
                survivor: { ...person(1, '1'), uuid: 'other-uuid' },
                results: [],
            })
            const store = makeStore(stores, 'shadow')

            await store.mergePersons({} as never, 0)

            // Which person survives decides where every later event in the
            // batch lands, and a row diff cannot see it: both sides end with
            // a person that looks plausible on its own.
            expect(divergences()).toContainEqual({ verb: 'mergePersons', field: 'survivor' })
        })

        it('records a source the two backends settled differently', async () => {
            const stores = makeStores()
            stores.pg.mergePersons.mockResolvedValue({
                survivor: person(1, '1'),
                results: [{ sourceDistinctId: 'anon-1', outcome: 'merged' }],
            })
            stores.personhogMock.mergePersons.mockResolvedValue({
                survivor: person(1, '1'),
                results: [{ sourceDistinctId: 'anon-1', outcome: 'skipped_already_identified' }],
            })
            const store = makeStore(stores, 'shadow')

            await store.mergePersons({} as never, 0)

            expect(divergences()).toContainEqual({ verb: 'mergePersons', field: 'outcome' })
        })

        it('tells shadow failures apart by class, not just by verb', async () => {
            class PersonhogFenceTimeoutError extends Error {}
            const stores = makeStores()
            stores.pg.fetchForUpdate.mockResolvedValue(person(1, '1'))
            stores.personhogMock.fetchForUpdate.mockRejectedValue(new PersonhogFenceTimeoutError('held'))
            const store = makeStore(stores, 'shadow')

            await store.fetchForUpdate(1, 'd1', 0)

            expect(personhogStoreShadowErrorsCounter.labels).toHaveBeenCalledWith({
                verb: 'fetchForUpdate',
                error: 'PersonhogFenceTimeoutError',
            })
        })

        it.each([
            ['unreachable', Code.Unavailable, 'Unavailable'],
            ['timed out', Code.DeadlineExceeded, 'DeadlineExceeded'],
            ['refusing', Code.FailedPrecondition, 'FailedPrecondition'],
        ])('separates an identity service that is %s', async (_case, code, label) => {
            const stores = makeStores()
            stores.pg.fetchForUpdate.mockResolvedValue(person(1, '1'))
            stores.personhogMock.fetchForUpdate.mockRejectedValue(new ConnectError('rpc failed', code))
            const store = makeStore(stores, 'shadow')

            await store.fetchForUpdate(1, 'd1', 0)

            // Every gRPC fault is the same ConnectError class, so labelling
            // by class puts unreachable, timed out, and refusing in one
            // number — the distinction a rollout most needs.
            expect(personhogStoreShadowErrorsCounter.labels).toHaveBeenCalledWith({
                verb: 'fetchForUpdate',
                error: label,
            })
        })

        it('says which side was empty when only one found a person', async () => {
            const stores = makeStores()
            stores.pg.fetchForUpdate.mockResolvedValue(null)
            stores.personhogMock.fetchForUpdate.mockResolvedValue(person(1, '1'))
            const store = makeStore(stores, 'shadow')

            await store.fetchForUpdate(1, 'd1', 0)

            // personhog not having seen a person yet is expected early in a
            // rollout and fades; personhog holding one Postgres lost never is.
            expect(divergences()).toContainEqual({ verb: 'fetchForUpdate', field: 'missing_authoritative' })
        })

        it.each([
            ['shutdown', async (store: RoutingPersonsStore) => await store.shutdown()],
            ['releaseBatch', (store: RoutingPersonsStore) => store.releaseBatch(0)],
        ])('a shadow %s failure does not reach the caller', async (verb, act) => {
            const stores = makeStores()
            stores.personhogMock.shutdown.mockRejectedValue(new Error('lanes still hold ops'))
            stores.personhogMock.abandonBatch.mockImplementation(() => {
                throw new Error('release blew up')
            })
            const store = makeStore(stores, 'shadow')

            // Shadow's contract is that the non-authoritative backend
            // cannot fail the caller; release and shutdown were the two
            // paths that still could.
            await expect(Promise.resolve(act(store))).resolves.not.toThrow()
            expect(personhogStoreShadowErrorsCounter.labels).toHaveBeenCalledWith({
                verb,
                error: 'Error',
            })
        })

        it('reads a shadow answer of undefined as absence, not as a comparator fault', async () => {
            const stores = makeStores()
            stores.pg.fetchForUpdate.mockResolvedValue(person(1, '1'))
            stores.personhogMock.fetchForUpdate.mockResolvedValue(undefined as never)
            const store = makeStore(stores, 'shadow')

            await expect(store.fetchForUpdate(1, 'd1', 0)).resolves.toEqual(person(1, '1'))

            // Dereferencing it would blame the backend for the comparator's
            // own crash, during the rollout the comparator exists to inform.
            expect(divergences()).toContainEqual({ verb: 'fetchForUpdate', field: 'missing_shadow' })
            expect(personhogStoreShadowErrorsCounter.labels).not.toHaveBeenCalled()
            expect(personhogStoreShadowCompareFailedCounter.labels).not.toHaveBeenCalled()
        })

        it('counts a comparator fault as its own, never as the backend failing', async () => {
            const stores = makeStores()
            stores.pg.fetchForUpdate.mockResolvedValue(person(1, '1'))
            // A person-shaped answer whose properties getter throws: the
            // comparison cannot complete, but the backend answered fine.
            stores.personhogMock.fetchForUpdate.mockResolvedValue({
                ...person(1, '1'),
                get properties(): never {
                    throw new Error('exploding properties')
                },
            } as never)
            const store = makeStore(stores, 'shadow')

            await expect(store.fetchForUpdate(1, 'd1', 0)).resolves.toEqual(person(1, '1'))

            expect(personhogStoreShadowCompareFailedCounter.labels).toHaveBeenCalledWith({ verb: 'fetchForUpdate' })
            expect(personhogStoreShadowErrorsCounter.labels).not.toHaveBeenCalled()
        })
    })

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

    describe('personhog mode', () => {
        it('routes every verb to personhog, never touching pg', async () => {
            const stores = makeStores()
            const store = makeStore(stores, 'personhog')

            await store.fetchForUpdate(1, 'a', 0)
            await store.fetchForUpdate(2, 'b', 0)
            expect(stores.personhogMock.fetchForUpdate).toHaveBeenCalledTimes(2)
            expect(stores.pg.fetchForUpdate).not.toHaveBeenCalled()
        })

        it('a personhog flush failure propagates, because the store is authoritative', async () => {
            const stores = makeStores()
            stores.personhogMock.flush.mockRejectedValue(new Error('leader down'))
            const store = makeStore(stores, 'personhog')
            await expect(store.flush()).rejects.toThrow('leader down')
        })

        it('mergePersons routes to the personhog store', async () => {
            const stores = makeStores()
            const saga = emptyMergeResult()
            stores.personhogMock.mergePersons.mockResolvedValue(saga)
            const store = makeStore(stores, 'personhog')
            await expect(store.mergePersons({} as never, 0)).resolves.toBe(saga)
            expect(stores.pg.mergePersons).not.toHaveBeenCalled()
        })

        it('flush never runs the pg side, and returns the personhog results', async () => {
            const stores = makeStores()
            const store = makeStore(stores, 'personhog')
            await expect(store.flush()).resolves.toEqual([])
            expect(stores.personhogMock.flush).toHaveBeenCalled()
            expect(stores.pg.flush).not.toHaveBeenCalled()
        })
    })

    describe('shadow mode', () => {
        it('pg is authoritative and the personhog verb runs shadowed', async () => {
            const stores = makeStores()
            stores.pg.fetchForUpdate.mockResolvedValue(person(1, '7'))
            stores.personhogMock.fetchForUpdate.mockResolvedValue(person(1, '99'))
            const store = makeStore(stores, 'shadow')

            const result = await store.fetchForUpdate(1, 'a', 0)

            expect(result?.id).toBe('7')
            expect(stores.personhogMock.fetchForUpdate).toHaveBeenCalled()
        })

        it('a shadow failure is swallowed and counted, never failing the batch', async () => {
            const stores = makeStores()
            stores.pg.fetchForUpdate.mockResolvedValue(person(1, '7'))
            stores.personhogMock.fetchForUpdate.mockRejectedValue(new Error('identity down'))
            const store = makeStore(stores, 'shadow')

            const result = await store.fetchForUpdate(1, 'a', 0)

            expect(result?.id).toBe('7')
            expect(personhogStoreShadowErrorsCounter.labels).toHaveBeenCalledWith({
                verb: 'fetchForUpdate',
                error: 'Error',
            })
        })

        it('a shadow verb that outruns its ceiling is abandoned, not waited out', async () => {
            // The shadow leg is awaited, so an unbounded one spends the
            // consumer's poll budget and costs the group its membership.
            jest.useFakeTimers()
            try {
                const stores = makeStores()
                stores.pg.fetchForUpdate.mockResolvedValue(person(1, '7'))
                stores.personhogMock.fetchForUpdate.mockReturnValue(new Promise(() => {}))
                const store = makeStore(stores, 'shadow')

                const pending = store.fetchForUpdate(1, 'a', 0)
                let settled = false
                void pending.then(() => (settled = true))
                await Promise.resolve()
                expect(settled).toBe(false)

                jest.advanceTimersByTime(60_000)
                const result = await pending

                expect(result?.id).toBe('7')
                expect(personhogStoreShadowErrorsCounter.labels).toHaveBeenCalledWith({
                    verb: 'fetchForUpdate',
                    error: 'ShadowVerbTimeoutError',
                })
            } finally {
                jest.useRealTimers()
            }
        })

        it('a shadow flush failure is swallowed', async () => {
            const stores = makeStores()
            stores.personhogMock.flush.mockRejectedValue(new Error('leader down'))
            const store = makeStore(stores, 'shadow')
            await expect(store.flush()).resolves.toEqual([])
        })

        it('the shadow leg completes before the routed call returns', async () => {
            // The swallow-and-count tests observe failures synchronously, so
            // a shadow leg degraded to fire-and-forget would pass them as
            // timing flakes rather than failing red. This pins the await:
            // the routed call must not return while the shadow is running.
            const stores = makeStores()
            stores.pg.fetchForUpdate.mockResolvedValue(person(1, '7'))
            let shadowDone = false
            stores.personhogMock.fetchForUpdate.mockImplementation(async () => {
                await new Promise((resolve) => setImmediate(resolve))
                shadowDone = true
                return null
            })
            const store = makeStore(stores, 'shadow')

            await store.fetchForUpdate(1, 'a', 0)

            expect(shadowDone).toBe(true)
        })

        it('shadow createPerson hands both backends the same uuid and answers pg', async () => {
            // Creation is the one write where the caller supplies identity;
            // both backends must receive it unchanged or the shadow's rows
            // diverge on the key downstream data is joined by.
            const stores = makeStores()
            const pgResult = { success: true as const, person: person(1, '7'), messages: [], created: true }
            stores.pg.createPerson.mockResolvedValue(pgResult as never)
            stores.personhogMock.createPerson.mockResolvedValue({
                success: true,
                person: person(1, '99'),
                messages: [],
                created: true,
            } as never)
            const store = makeStore(stores, 'shadow')

            const result = await store.createPerson(
                DateTime.fromMillis(3_600_000, { zone: 'utc' }),
                {},
                {},
                {},
                1,
                null,
                false,
                'caller-supplied-uuid',
                { distinctId: 'd1' },
                undefined,
                undefined,
                0
            )

            expect(result).toBe(pgResult)
            expect(stores.pg.createPerson.mock.calls[0][7]).toBe('caller-supplied-uuid')
            expect(stores.personhogMock.createPerson.mock.calls[0][7]).toBe('caller-supplied-uuid')
        })

        it('mergePersons replays the same request against the personhog backend, pg staying authoritative', async () => {
            const stores = makeStores()
            const pgResult = { survivor: person(1, '7'), results: [] }
            stores.pg.mergePersons.mockResolvedValue(pgResult)
            const store = makeStore(stores, 'shadow')
            const request = { teamId: 1, targetDistinctId: 'd' } as never

            await expect(store.mergePersons(request, 0)).resolves.toBe(pgResult)

            expect(stores.pg.mergePersons).toHaveBeenCalledWith(request, 0)
            expect(stores.personhogMock.mergePersons).toHaveBeenCalledWith(request, 0)
        })

        it('a shadow merge failure is swallowed and counted, never failing the batch', async () => {
            const stores = makeStores()
            stores.pg.mergePersons.mockResolvedValue(emptyMergeResult())
            stores.personhogMock.mergePersons.mockRejectedValue(new Error('identity down'))
            const store = makeStore(stores, 'shadow')

            await expect(store.mergePersons({} as never, 0)).resolves.toEqual(emptyMergeResult())
            expect(personhogStoreShadowErrorsCounter.labels).toHaveBeenCalledWith({
                verb: 'mergePersons',
                error: 'Error',
            })
        })

        it('prefetch warms both worlds', async () => {
            const stores = makeStores()
            const store = makeStore(stores, 'shadow')
            await store.prefetchPersons([{ teamId: 1, distinctId: 'd', batchId: 0 }])
            expect(stores.pg.prefetchPersons).toHaveBeenCalled()
            expect(stores.personhogMock.prefetchPersons).toHaveBeenCalled()
        })

        it('getFlushStats counts a batch once when both worlds reference it', () => {
            const stores = makeStores()
            stores.pg.getFlushStats.mockReturnValue({ dirtyEntryCount: 2, referencedBatchCount: 1, cacheEntryCount: 3 })
            stores.personhogMock.getFlushStats.mockReturnValue({
                dirtyEntryCount: 1,
                referencedBatchCount: 1,
                cacheEntryCount: 2,
            })
            const store = makeStore(stores, 'shadow')
            expect(store.getFlushStats()).toEqual({ dirtyEntryCount: 3, referencedBatchCount: 1, cacheEntryCount: 5 })
        })
    })

    describe('shadow writes resolve the personhog backend person', () => {
        it.each([
            [
                'applyEventOps',
                (store: RoutingPersonsStore) => store.applyEventOps(person(1, '7'), ops, 'd1', 0),
                (m: jest.Mocked<PersonsStore>) => m.applyEventOps,
            ],
            [
                'updatePersonWithPropertiesDiffForUpdate',
                (store: RoutingPersonsStore) =>
                    store.updatePersonWithPropertiesDiffForUpdate(person(1, '7'), { a: '1' }, [], {}, 'd1', 0),
                (m: jest.Mocked<PersonsStore>) => m.updatePersonWithPropertiesDiffForUpdate,
            ],
        ] as const)('%s writes the shadow backend id, not the pg id', async (_verb, call, member) => {
            const stores = makeStores()
            stores.pg.applyEventOps.mockResolvedValue([person(1, '7'), []])
            stores.pg.updatePersonWithPropertiesDiffForUpdate.mockResolvedValue([person(1, '7'), [], true])
            stores.personhogMock.fetchForUpdate.mockResolvedValue(person(1, '99'))
            stores.personhogMock.applyEventOps.mockResolvedValue([person(1, '99'), []])
            stores.personhogMock.updatePersonWithPropertiesDiffForUpdate.mockResolvedValue([person(1, '99'), [], true])
            const store = makeStore(stores, 'shadow')

            await call(store)

            const shadowArgs = member(stores.personhogMock).mock.calls[0]
            expect((shadowArgs[0] as InternalPerson).id).toBe('99')
        })

        it('skips the shadow write, counted, when the person does not exist in the personhog backend', async () => {
            const stores = makeStores()
            stores.pg.applyEventOps.mockResolvedValue([person(1, '7'), []])
            stores.personhogMock.fetchForUpdate.mockResolvedValue(null)
            const store = makeStore(stores, 'shadow')

            const [result] = await store.applyEventOps(person(1, '7'), ops, 'd1', 0)

            expect(result.id).toBe('7')
            expect(stores.personhogMock.applyEventOps).not.toHaveBeenCalled()
            expect(personhogStoreShadowSkipsCounter.labels).toHaveBeenCalledWith({ verb: 'applyEventOps' })
        })
    })

    it('shutdown closes the personhog side even when pg shutdown fails', async () => {
        const stores = makeStores()
        stores.pg.shutdown.mockRejectedValue(new Error('pg teardown failed'))
        const store = makeStore(stores, 'shadow')

        await expect(store.shutdown()).rejects.toThrow('pg teardown failed')
        expect(stores.personhogMock.shutdown).toHaveBeenCalled()
    })

    it('a shadow release abandons the personhog batch rather than keeping it', () => {
        // A shadow flush failure already acked the batch on the pg side, so
        // a plain release would retain the unwritten lanes forever; hours
        // of identity outage would grow them without bound inside the
        // authoritative process.
        const stores = makeStores()
        const store = makeStore(stores, 'shadow')
        store.releaseBatch(4)
        expect(stores.pg.releaseBatch).toHaveBeenCalledWith(4)
        expect(stores.personhogMock.abandonBatch).toHaveBeenCalledWith(4)
        expect(stores.personhogMock.releaseBatch).not.toHaveBeenCalled()
    })

    it('a personhog-mode release keeps unwritten lanes for the next flush', () => {
        const stores = makeStores()
        const store = makeStore(stores, 'personhog')
        store.releaseBatch(4)
        expect(stores.personhogMock.releaseBatch).toHaveBeenCalledWith(4)
        expect(stores.personhogMock.abandonBatch).not.toHaveBeenCalled()
    })
})
