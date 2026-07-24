import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { signalSourcesLogic } from './signalSourcesLogic'

const githubSource = {
    id: 'src-1',
    source_type: 'Github',
    schemas: [
        { id: 'sc-1', name: 'workflow_runs', should_sync: true },
        { id: 'sc-2', name: 'pull_requests', should_sync: true },
        { id: 'sc-3', name: 'workflow_jobs', should_sync: true },
    ],
}

describe('signalSourcesLogic', () => {
    let logic: ReturnType<typeof signalSourcesLogic.build>
    let warehouseSources: Record<string, unknown>[]

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
})
