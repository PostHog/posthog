import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, ExternalDataJobStatus, ExternalDataSource, ExternalDataSourceSchema } from '~/types'

import { signalSourcesLogic } from './signalSourcesLogic'
import { SignalSourceProduct, SignalSourceType } from './types'

const githubSchema = (
    id: string,
    name: string,
    overrides: Partial<ExternalDataSourceSchema> = {}
): ExternalDataSourceSchema => ({
    id,
    name,
    label: null,
    should_sync: true,
    incremental: false,
    sync_type: 'full_refresh',
    sync_time_of_day: null,
    latest_error: null,
    incremental_field: null,
    incremental_field_type: null,
    sync_frequency: '24hour',
    primary_key_columns: null,
    ...overrides,
})

const githubSource: ExternalDataSource = {
    id: 'src-1',
    source_id: 'source-1',
    connection_id: 'connection-1',
    status: ExternalDataJobStatus.Completed,
    source_type: 'Github',
    prefix: null,
    description: null,
    created_via: 'web',
    latest_error: null,
    schemas: [
        githubSchema('sc-0', 'issues'),
        githubSchema('sc-1', 'workflow_runs'),
        githubSchema('sc-2', 'pull_requests'),
        githubSchema('sc-3', 'workflow_jobs'),
    ],
    sync_frequency: '24hour',
    job_inputs: {},
    revenue_analytics_config: { enabled: false, include_invoiceless_charges: false },
    user_access_level: AccessControlLevel.Manager,
}

const sourceWith = (id: string, schemas: ExternalDataSourceSchema[]): ExternalDataSource => ({
    ...githubSource,
    id,
    schemas,
})

const githubIssuesConfig = {
    id: 'config-1',
    source_product: SignalSourceProduct.Github,
    source_type: SignalSourceType.Issue,
    enabled: true,
    config: {},
    created_at: '2026-07-27T00:00:00Z',
    updated_at: '2026-07-27T00:00:00Z',
    status: null,
}

describe('signalSourcesLogic', () => {
    let logic: ReturnType<typeof signalSourcesLogic.build>
    let warehouseSources: ExternalDataSource[]

    beforeEach(() => {
        warehouseSources = []
        useMocks({
            get: {
                '/api/environments/:team_id/external_data_sources/': () => [
                    200,
                    { results: warehouseSources, count: warehouseSources.length, next: null, previous: null },
                ],
                '/api/projects/:team_id/signals/source_configs/': () => [
                    200,
                    { results: [], count: 0, next: null, previous: null },
                ],
            },
            put: {
                '/api/projects/:team_id/engineering_analytics/ci-signals-config/': () => [
                    200,
                    { configured: true, enabled: true, sync_status: 'completed' },
                ],
            },
        })
        initKeaTests()
        logic = signalSourcesLogic()
        logic.mount()
    })

    afterEach(() => {
        // Spies on the shared `api` singleton outlive the test that set them and leak into the next.
        jest.restoreAllMocks()
        logic?.unmount()
    })

    // The cached sources list is null right after mount (loadSources is debounced). Reading it
    // directly misread that as "no source connected" and opened the connect form, duplicating an
    // already-connected source. Enabling must reuse the existing source; only a genuinely empty
    // account should reach the connect form.
    it.each([
        {
            name: 'enables in place when a GitHub source exists but the list has not loaded',
            sources: [githubSource],
            action: 'loadCiSignalsConfigSuccess',
            setup: null,
        },
        {
            name: 'opens the connect form only when no GitHub source is connected',
            sources: [],
            action: 'openDataSourceSetup',
            setup: 'engineering_analytics',
        },
    ])('$name', async ({ sources, action, setup }) => {
        warehouseSources = sources
        expect(logic.values.dataWarehouseSources).toBeNull()

        await expectLogic(logic, () => {
            logic.actions.toggleCiSignals()
        }).toDispatchActions(['toggleCiSignals', action])

        expect(logic.values.dataSourceSetupSource).toBe(setup)
    })

    it('keeps an enabled source enabled when its config loads during the source lookup', async () => {
        let resolveSources!: (sources: Awaited<ReturnType<typeof api.externalDataSources.list>>) => void
        const sourcesPromise = new Promise<Awaited<ReturnType<typeof api.externalDataSources.list>>>((resolve) => {
            resolveSources = resolve
        })
        const listSources = jest.spyOn(api.externalDataSources, 'list').mockReturnValue(sourcesPromise)
        const updateSourceConfig = jest.spyOn(api.signalSourceConfigs, 'update').mockResolvedValue(githubIssuesConfig)

        logic.actions.initiateDataWarehouseSourceToggle('github')
        expect(logic.values.isGithubIssuesToggling).toBe(true)
        logic.actions.loadSourceConfigsSuccess([githubIssuesConfig])
        resolveSources({
            results: [githubSource],
            next: null,
            previous: null,
        })

        await expectLogic(logic).toFinishAllListeners()

        expect(listSources).toHaveBeenCalledTimes(1)
        expect(updateSourceConfig).not.toHaveBeenCalled()
        expect(logic.values.githubIssuesConfig?.enabled).toBe(true)
        expect(logic.values.isGithubIssuesToggling).toBe(false)
    })

    it('ignores repeated clicks while the source lookup is pending', async () => {
        let resolveSources!: (sources: Awaited<ReturnType<typeof api.externalDataSources.list>>) => void
        const sourcesPromise = new Promise<Awaited<ReturnType<typeof api.externalDataSources.list>>>((resolve) => {
            resolveSources = resolve
        })
        const listSources = jest.spyOn(api.externalDataSources, 'list').mockReturnValue(sourcesPromise)
        const createSourceConfig = jest.spyOn(api.signalSourceConfigs, 'create').mockResolvedValue(githubIssuesConfig)
        logic.actions.loadSourceConfigsSuccess([])

        logic.actions.initiateDataWarehouseSourceToggle('github')
        logic.actions.initiateDataWarehouseSourceToggle('github')

        expect(logic.values.isGithubIssuesToggling).toBe(true)
        expect(listSources).toHaveBeenCalledTimes(1)
        resolveSources({
            results: [githubSource],
            next: null,
            previous: null,
        })

        await expectLogic(logic).toFinishAllListeners()

        expect(createSourceConfig).toHaveBeenCalledTimes(1)
        expect(logic.values.isGithubIssuesToggling).toBe(false)
    })

    // Forcing a required table to sync sent a bare should_sync, which the backend rejects for a
    // schema that never had a sync method ("Sync type must be set up first before enabling schema"),
    // so enabling a signal failed outright on any table the team had not configured by hand.
    it.each([
        {
            name: 'asks the backend for sync defaults when the schema has no sync method',
            sources: [
                sourceWith('src-a', [
                    githubSchema('sc-a', 'PostHog/posthog.issues', { should_sync: false, sync_type: null }),
                ]),
            ],
            expectedCalls: [['src-a', [{ id: 'sc-a', should_sync: true, apply_sync_defaults: true }]]],
        },
        {
            name: 'leaves an already-configured schema to its own sync method',
            sources: [
                sourceWith('src-a', [
                    githubSchema('sc-a', 'issues', { should_sync: false, sync_type: 'full_refresh' }),
                ]),
            ],
            expectedCalls: [['src-a', [{ id: 'sc-a', should_sync: true }]]],
        },
        {
            name: 'still reaches every connected source of that type, one request each',
            sources: [
                sourceWith('src-a', [githubSchema('sc-a', 'issues', { should_sync: false, sync_type: null })]),
                sourceWith('src-b', [githubSchema('sc-b', 'issues', { should_sync: true })]),
                sourceWith('src-c', [githubSchema('sc-c', 'issues', { should_sync: false, sync_type: 'incremental' })]),
            ],
            expectedCalls: [
                ['src-a', [{ id: 'sc-a', should_sync: true, apply_sync_defaults: true }]],
                ['src-c', [{ id: 'sc-c', should_sync: true }]],
            ],
        },
    ])('$name', async ({ sources, expectedCalls }) => {
        const bulkUpdateSchemas = jest.spyOn(api.externalDataSources, 'bulkUpdateSchemas').mockResolvedValue([])
        jest.spyOn(api.signalSourceConfigs, 'create').mockResolvedValue(githubIssuesConfig)
        warehouseSources = sources
        logic.actions.loadSourceConfigsSuccess([])

        logic.actions.initiateDataWarehouseSourceToggle('github')
        await expectLogic(logic).toFinishAllListeners()

        expect(bulkUpdateSchemas.mock.calls).toEqual(expectedCalls)
        expect(logic.values.dataSourceSetupSource).toBeNull()
    })
})
