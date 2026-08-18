import { personhogStoreShadowErrorsCounter, personhogStoreShadowSkipsCounter } from '~/common/persons/metrics'
import { InternalPerson } from '~/types'

import { EventOps } from './person-update'
import { PersonhogPersonsStore } from './personhog-persons-store'
import { MergePersonsResult, PersonsBackend, PersonsStore } from './persons-store'
import { RoutingPersonsStore, assertPersonsStoreModeConfig, parsePersonsStoreMode } from './routing-persons-store'

jest.mock('~/common/persons/metrics', () => ({
    personhogStoreShadowErrorsCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
    personhogStoreShadowSkipsCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
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
        const personhogMock = mockStore()
        const personhog = personhogMock as unknown as PersonhogPersonsStore
        return { pg, personhogMock, personhog }
    }

    const makeStore = (stores: ReturnType<typeof makeStores>, mode: 'personhog' | 'shadow') =>
        new RoutingPersonsStore(stores.pg, stores.personhog, mode)

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
            expect(personhogStoreShadowErrorsCounter.labels).toHaveBeenCalledWith({ verb: 'fetchForUpdate' })
        })

        it('a shadow flush failure is swallowed', async () => {
            const stores = makeStores()
            stores.personhogMock.flush.mockRejectedValue(new Error('leader down'))
            const store = makeStore(stores, 'shadow')
            await expect(store.flush()).resolves.toEqual([])
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
            expect(personhogStoreShadowErrorsCounter.labels).toHaveBeenCalledWith({ verb: 'mergePersons' })
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

    it('releaseBatch releases both worlds', () => {
        const stores = makeStores()
        const store = makeStore(stores, 'shadow')
        store.releaseBatch(4)
        expect(stores.pg.releaseBatch).toHaveBeenCalledWith(4)
        expect(stores.personhogMock.releaseBatch).toHaveBeenCalledWith(4)
    })
})
