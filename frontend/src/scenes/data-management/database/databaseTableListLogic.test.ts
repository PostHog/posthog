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
})
