import { personhogStoreShadowErrorsCounter, personhogStoreShadowSkipsCounter } from '~/common/persons/metrics'
import { InternalPerson } from '~/types'

import { EventOps } from './person-update'
import { PersonhogPersonsStore } from './personhog-persons-store'
import { PersonsStore } from './persons-store'
import { RoutingPersonsStore, assertPersonsStoreModeConfig, parsePersonsStoreMode } from './routing-persons-store'

jest.mock('~/common/persons/metrics', () => ({
    personhogStoreShadowErrorsCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
    personhogStoreShadowSkipsCounter: { labels: jest.fn().mockReturnValue({ inc: jest.fn() }) },
}))

/**
 * A complete, compile-checked PersonsStore mock: the annotation forces
 * every interface member to exist, so an interface change breaks this
 * factory at compile time instead of leaving stale mocks that only fail
 * when a newly routed method runs.
 */
function mockStore(): jest.Mocked<PersonsStore> {
    return {
        inTransaction: jest.fn(),
        fetchForChecking: jest.fn().mockResolvedValue(null),
        fetchForUpdate: jest.fn().mockResolvedValue(null),
        fetchPersonsForUpdateByDistinctIds: jest.fn().mockResolvedValue([]),
        createPerson: jest.fn().mockResolvedValue({ success: true }),
        updatePersonForMerge: jest.fn(),
        applyEventOps: jest.fn(),
        updatePersonWithPropertiesDiffForUpdate: jest.fn(),
        deletePerson: jest.fn().mockResolvedValue([]),
        claimLifecycleMarks: jest.fn().mockResolvedValue(undefined),
        releaseLifecycleMarks: jest.fn().mockResolvedValue(undefined),
        isPersonLive: jest.fn().mockResolvedValue(true),
        addDistinctId: jest.fn().mockResolvedValue([]),
        moveDistinctIds: jest.fn().mockResolvedValue({ success: true }),
        moveDistinctIdsFromPersons: jest.fn().mockResolvedValue({ success: true }),
        deletePersons: jest.fn().mockResolvedValue([]),
        countDistinctIdsForPersons: jest.fn().mockResolvedValue(new Map()),
        updateCohortsAndFeatureFlagsForMerge: jest.fn().mockResolvedValue(undefined),
        updateCohortsAndFeatureFlagsForMergeBatch: jest.fn().mockResolvedValue(undefined),
        personPropertiesSize: jest.fn().mockResolvedValue(0),
        fetchPersonDistinctIds: jest.fn().mockResolvedValue([]),
        shutdown: jest.fn().mockResolvedValue(undefined),
        removeDistinctIdFromCache: jest.fn(),
        prefetchPersons: jest.fn().mockResolvedValue(undefined),
        flush: jest.fn().mockResolvedValue([]),
        releaseBatch: jest.fn(),
        getFlushStats: jest.fn().mockReturnValue({ dirtyEntryCount: 0, referencedBatchCount: 0, cacheEntryCount: 0 }),
    }
}

describe('RoutingPersonsStore', () => {
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

    describe('shadow writes resolve the personhog world person', () => {
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
        ] as const)('%s ships the shadow world id, not the pg id', async (_verb, call, member) => {
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

        it('skips the shadow write, counted, when the person does not exist in the personhog world', async () => {
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

    describe('merge execution routes to the team world, never across it', () => {
        it.each([
            ['deletePersons', (s: RoutingPersonsStore) => s.deletePersons([person(1)], 'd'), 'deletePersons'],
            [
                'addDistinctId',
                (s: RoutingPersonsStore) => s.addDistinctId(person(1), 'd', 0, undefined, 0),
                'addDistinctId',
            ],
            [
                'updatePersonForMerge',
                (s: RoutingPersonsStore) => s.updatePersonForMerge(person(1), {}, 'd', 0),
                'updatePersonForMerge',
            ],
            [
                'claimLifecycleMarks',
                (s: RoutingPersonsStore) => s.claimLifecycleMarks('op', 1, [], 'd'),
                'claimLifecycleMarks',
            ],
        ] as const)('%s reaches the personhog store for a routed team', async (_name, call, member) => {
            const stores = makeStores()
            const store = makeStore(stores, 'personhog')

            await call(store)

            expect(stores.personhogMock[member as keyof PersonsStore]).toHaveBeenCalled()
            expect(stores.pg[member as keyof PersonsStore]).not.toHaveBeenCalled()
        })

        it('shadow mode runs merges on pg and swallows the personhog placeholder', async () => {
            const stores = makeStores()
            stores.personhogMock.deletePersons.mockRejectedValue(new Error('no personhog RPC: merge saga'))
            const store = makeStore(stores, 'shadow')

            await store.deletePersons([person(1)], 'd')

            expect(stores.pg.deletePersons).toHaveBeenCalled()
            expect(personhogStoreShadowErrorsCounter.labels).toHaveBeenCalledWith({ verb: 'deletePersons' })
        })
    })

    describe('inTransaction routes by mode', () => {
        it('personhog mode reaches the personhog store, whose placeholder answers', () => {
            const stores = makeStores()
            const store = makeStore(stores, 'personhog')
            const cb = () => Promise.resolve('x')

            void store.inTransaction('merge', cb)

            expect(stores.personhogMock.inTransaction).toHaveBeenCalledWith('merge', cb)
            expect(stores.pg.inTransaction).not.toHaveBeenCalled()
        })

        it('shadow mode runs the transaction on pg exactly once, unshadowed', () => {
            const stores = makeStores()
            const store = makeStore(stores, 'shadow')
            const cb = () => Promise.resolve('x')

            void store.inTransaction('merge', cb)

            expect(stores.pg.inTransaction).toHaveBeenCalledWith('merge', cb)
            expect(stores.personhogMock.inTransaction).not.toHaveBeenCalled()
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
