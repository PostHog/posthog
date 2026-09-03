import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { urls } from 'scenes/urls'

import { performQuery } from '~/queries/query'
import { initKeaTests } from '~/test/init'

import { databaseTableListLogic } from './databaseTableListLogic'

jest.mock('~/queries/query')

describe('databaseTableListLogic', () => {
    let logic: ReturnType<typeof databaseTableListLogic.build>

    beforeEach(() => {
        initKeaTests()
        ;(performQuery as jest.Mock).mockResolvedValue({
            tables: {},
            joins: [],
        })
    })

    afterEach(() => {
        logic?.unmount()
        window.history.replaceState({}, '', urls.sqlEditor())
        jest.clearAllMocks()
    })

    it('does not read sql editor connection hashes or auto-load on mount', () => {
        window.history.replaceState({}, '', `${urls.sqlEditor()}#c=conn-123`)

        logic = databaseTableListLogic()
        logic.mount()

        expect(logic.values.connectionId).toBeNull()
        expect(performQuery).not.toHaveBeenCalled()
    })

    it('does not auto-load on mount without a connection hash', () => {
        window.history.replaceState({}, '', urls.sqlEditor())

        logic = databaseTableListLogic()
        logic.mount()

        expect(performQuery).not.toHaveBeenCalled()
    })

    it('deduplicates in-flight schema loads for the same connection', async () => {
        let resolveQuery: ((value: { tables: Record<string, never>; joins: never[] }) => void) | undefined
        ;(performQuery as jest.Mock).mockImplementation(
            () =>
                new Promise((resolve) => {
                    resolveQuery = resolve
                })
        )

        logic = databaseTableListLogic()
        logic.mount()
        logic.actions.setConnection('conn-123')

        const firstRequest = logic.asyncActions.loadDatabase()
        const secondRequest = logic.asyncActions.loadDatabase()

        expect(performQuery).toHaveBeenCalledTimes(1)

        resolveQuery?.({ tables: {}, joins: [] })

        await Promise.all([firstRequest, secondRequest])
        expect(performQuery).toHaveBeenCalledTimes(1)
    })

    it.each([
        { name: 'main path', concurrentLoads: 1 },
        { name: 'dedup branch', concurrentLoads: 2 },
    ])('does not crash when unmounted mid-load ($name)', async ({ concurrentLoads }) => {
        let resolveQuery: ((value: { tables: Record<string, never>; joins: never[] }) => void) | undefined
        ;(performQuery as jest.Mock).mockImplementation(
            () =>
                new Promise((resolve) => {
                    resolveQuery = resolve
                })
        )

        const localLogic = databaseTableListLogic()
        localLogic.mount()

        const requests = Array.from({ length: concurrentLoads }, () => localLogic.asyncActions.loadDatabase())
        expect(performQuery).toHaveBeenCalledTimes(1)

        localLogic.unmount()
        resolveQuery?.({ tables: {}, joins: [] })
        await Promise.all(requests)

        expect(posthog.captureException).not.toHaveBeenCalled()
    })

    it('refreshDatabaseSchema issues a fresh request instead of piggybacking on an in-flight load', () => {
        ;(performQuery as jest.Mock).mockImplementation(() => new Promise(() => {}))

        logic = databaseTableListLogic()
        logic.mount()
        logic.actions.setConnection('conn-123')

        logic.actions.loadDatabase()
        expect(performQuery).toHaveBeenCalledTimes(1)

        // A plain reload would dedupe onto the in-flight request and return its (pre-mutation)
        // result; the forced refresh must issue its own request.
        logic.actions.refreshDatabaseSchema()
        expect(performQuery).toHaveBeenCalledTimes(2)
    })

    it('discards a superseded in-flight response so a refreshed post-deletion schema is not overwritten', async () => {
        let resolveStale: ((value: { tables: Record<string, unknown>; joins: never[] }) => void) | undefined
        let resolveFresh: ((value: { tables: Record<string, unknown>; joins: never[] }) => void) | undefined
        ;(performQuery as jest.Mock)
            .mockImplementationOnce(() => new Promise((resolve) => (resolveStale = resolve)))
            .mockImplementationOnce(() => new Promise((resolve) => (resolveFresh = resolve)))

        logic = databaseTableListLogic()
        logic.mount()

        const stalePreDeletion = logic.asyncActions.loadDatabase()
        const freshPostDeletion = logic.asyncActions.loadDatabase({ force: true })
        expect(performQuery).toHaveBeenCalledTimes(2)

        // The forced (post-deletion) refresh resolves first: the deleted view is gone.
        resolveFresh?.({ tables: {}, joins: [] })
        await freshPostDeletion
        expect(logic.values.views).toEqual([])

        // The older in-flight request resolves later, still carrying the deleted view. It is
        // superseded and must not clobber the refreshed schema.
        resolveStale?.({ tables: { my_view: { name: 'my_view', type: 'view' } }, joins: [] })
        await stalePreDeletion
        expect(logic.values.views).toEqual([])
    })

    it('resetConnectionScope drops the connection and reloads the project catalog', async () => {
        logic = databaseTableListLogic()
        logic.mount()
        logic.actions.setConnection('conn-123')
        await logic.asyncActions.loadDatabase()
        ;(performQuery as jest.Mock).mockClear()
        ;(performQuery as jest.Mock).mockResolvedValue({
            tables: { events: { name: 'events', type: 'posthog' } },
            joins: [],
        })

        // Without the reload, consumers that only fetch when `database` is empty would keep
        // rendering the connection's tables long after the SQL editor closed.
        logic.actions.resetConnectionScope()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.connectionId).toBeNull()
        expect(performQuery).toHaveBeenCalledTimes(1)
        expect((performQuery as jest.Mock).mock.calls[0][0]).toMatchObject({ connectionId: undefined })
        expect(logic.values.allTables.map((table) => table.name)).toEqual(['events'])
    })

    it('does not let a stale schema response overwrite the selected connection schema', async () => {
        let resolvePosthogQuery:
            | ((value: { tables: Record<string, { name: string; type: 'posthog' }>; joins: never[] }) => void)
            | undefined
        let resolveDirectQuery:
            | ((value: { tables: Record<string, { name: string; type: 'data_warehouse' }>; joins: never[] }) => void)
            | undefined

        ;(performQuery as jest.Mock)
            .mockImplementationOnce(
                () =>
                    new Promise((resolve) => {
                        resolvePosthogQuery = resolve
                    })
            )
            .mockImplementationOnce(
                () =>
                    new Promise((resolve) => {
                        resolveDirectQuery = resolve
                    })
            )

        logic = databaseTableListLogic()
        logic.mount()

        const posthogRequest = logic.asyncActions.loadDatabase()

        logic.actions.setConnection('conn-123')
        const directRequest = logic.asyncActions.loadDatabase()

        resolveDirectQuery?.({
            tables: {
                ducklake_accounts: { name: 'ducklake_accounts', type: 'data_warehouse' },
            },
            joins: [],
        })
        await directRequest

        expect(logic.values.allTables.map((table) => table.name)).toEqual(['ducklake_accounts'])

        resolvePosthogQuery?.({
            tables: {
                events: { name: 'events', type: 'posthog' },
            },
            joins: [],
        })
        await posthogRequest

        expect(logic.values.connectionId).toEqual('conn-123')
        expect(logic.values.allTables.map((table) => table.name)).toEqual(['ducklake_accounts'])
    })

    describe('lazy schema loading', () => {
        const shallowTables = {
            events: { name: 'events', type: 'posthog', fields: {} },
            persons: { name: 'persons', type: 'posthog', fields: {} },
        }
        const eventsFields = {
            uuid: { name: 'uuid', hogql_value: 'uuid', type: 'string', schema_valid: true },
        }

        const loadShallow = async (): Promise<void> => {
            ;(performQuery as jest.Mock).mockResolvedValueOnce({ tables: shallowTables, joins: [] })
            await logic.asyncActions.loadDatabase({ shallow: true })
        }

        beforeEach(() => {
            logic = databaseTableListLogic()
            logic.mount()
        })

        it('a shallow load requests no fields and marks the schema incomplete', async () => {
            await loadShallow()

            expect((performQuery as jest.Mock).mock.calls[0][0]).toMatchObject({ includeFields: false })
            expect(logic.values.databaseFieldsComplete).toBe(false)
            expect(logic.values.allTables.map((table) => table.name)).toEqual(['events', 'persons'])

            ;(performQuery as jest.Mock).mockResolvedValueOnce({ tables: shallowTables, joins: [] })
            await logic.asyncActions.loadDatabase({ force: true })
            expect(logic.values.databaseFieldsComplete).toBe(true)
        })

        it('hydrateTableFields merges the requested tables and flags missing ones as errors', async () => {
            await loadShallow()
            ;(performQuery as jest.Mock).mockResolvedValueOnce({
                tables: { events: { ...shallowTables.events, fields: eventsFields } },
                joins: [],
            })

            await logic.asyncActions.hydrateTableFields(['events', 'gone_table'])

            expect((performQuery as jest.Mock).mock.calls[1][0]).toMatchObject({
                tables: ['events'],
            })
            expect(logic.values.database?.tables['events'].fields).toEqual(eventsFields)
            expect(logic.values.database?.tables['persons'].fields).toEqual({})
            expect(logic.values.tableFieldsStatus).toMatchObject({ events: 'loaded' })
            // 'gone_table' isn't in the schema at all, so it's filtered before the request.
            expect(logic.values.tableFieldsStatus['gone_table']).toBeUndefined()
        })

        it('hydrateTableFields skips tables that are already loaded or loading', async () => {
            await loadShallow()
            ;(performQuery as jest.Mock).mockResolvedValueOnce({
                tables: { events: { ...shallowTables.events, fields: eventsFields } },
                joins: [],
            })
            await logic.asyncActions.hydrateTableFields(['events'])
            expect(performQuery).toHaveBeenCalledTimes(2)

            await logic.asyncActions.hydrateTableFields(['events'])
            expect(performQuery).toHaveBeenCalledTimes(2)
        })

        it('does not let a stale hydration failure overwrite fields loaded for another connection', async () => {
            logic.actions.setConnection('conn-old')
            await loadShallow()

            let rejectStaleHydration: ((reason?: unknown) => void) | undefined
            ;(performQuery as jest.Mock).mockImplementationOnce(
                () =>
                    new Promise<never>((_, reject) => {
                        rejectStaleHydration = reject
                    })
            )
            const staleHydration = logic.asyncActions.hydrateTableFields(['events'])

            logic.actions.setConnection('conn-new')
            await loadShallow()
            ;(performQuery as jest.Mock).mockResolvedValueOnce({
                tables: { events: { ...shallowTables.events, fields: eventsFields } },
                joins: [],
            })
            await logic.asyncActions.hydrateTableFields(['events'])

            expect(logic.values.database?.tables['events'].fields).toEqual(eventsFields)
            expect(logic.values.tableFieldsStatus).toMatchObject({ events: 'loaded' })

            rejectStaleHydration?.(new Error('Stale connection failed'))
            await staleHydration

            expect(logic.values.database?.tables['events'].fields).toEqual(eventsFields)
            expect(logic.values.tableFieldsStatus).toMatchObject({ events: 'loaded' })
        })

        it('treats a requested table missing from the response as terminal', async () => {
            await loadShallow()
            ;(performQuery as jest.Mock).mockResolvedValueOnce({ tables: {}, joins: [] })

            await logic.asyncActions.hydrateTableFields(['events'])

            expect(logic.values.tableFieldsStatus).toMatchObject({ events: 'missing' })
            expect(logic.values.database?.tables['events']).toBeUndefined()
            expect(logic.values.databaseFieldsComplete).toBe(false)

            ;(performQuery as jest.Mock).mockResolvedValueOnce({
                tables: { persons: { ...shallowTables.persons, fields: eventsFields } },
                joins: [],
            })
            await logic.asyncActions.hydrateTableFields(['events', 'persons'])

            expect(logic.values.databaseFieldsComplete).toBe(true)
            expect((performQuery as jest.Mock).mock.calls[2][0]).toMatchObject({ tables: ['persons'] })

            await logic.asyncActions.hydrateTableFields(['events'])
            expect(performQuery).toHaveBeenCalledTimes(3)
        })

        it('ensureAllTableFields hydrates every table in place and marks the schema complete', async () => {
            await loadShallow()
            ;(performQuery as jest.Mock).mockResolvedValueOnce({
                tables: {
                    events: { ...shallowTables.events, fields: eventsFields },
                    persons: { ...shallowTables.persons, fields: eventsFields },
                },
                joins: [],
            })

            logic.actions.ensureAllTableFields()
            await expectLogic(logic).toFinishAllListeners()

            // Upgrades through the merge path, so `databaseLoading` never blanks consumers.
            expect((performQuery as jest.Mock).mock.calls[1][0]).toMatchObject({
                tables: ['events', 'persons'],
            })
            expect(logic.values.databaseFieldsComplete).toBe(true)
            expect(logic.values.database?.tables['persons'].fields).toEqual(eventsFields)
        })

        it('a full load does not piggyback on an in-flight shallow request', () => {
            ;(performQuery as jest.Mock).mockImplementation(() => new Promise(() => {}))

            logic.actions.loadDatabase({ shallow: true })
            expect(performQuery).toHaveBeenCalledTimes(1)

            logic.actions.loadDatabase()
            expect(performQuery).toHaveBeenCalledTimes(2)
            expect((performQuery as jest.Mock).mock.calls[1][0].includeFields).toBeUndefined()
        })
    })
})
