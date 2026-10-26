import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { clearAllCachedHasData } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ExportType } from '~/exporter/types'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { dataWarehouseSetupLogic } from 'products/data_warehouse/frontend/emptyState/dataWarehouseSetupLogic'

import { sampleDataStateLogic } from './sampleDataStateLogic'

describe('sampleDataStateLogic', () => {
    let logic: ReturnType<typeof sampleDataStateLogic.build>

    afterEach(() => {
        delete (window as { POSTHOG_EXPORTED_DATA?: unknown }).POSTHOG_EXPORTED_DATA
    })

    // The global is read inside the selector, so it must be in place before the selector first
    // computes (as on real shared pages, where Django injects it before React runs).
    function mount(currentTeam: unknown): void {
        clearAllCachedHasData()
        initKeaTests()
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess(currentTeam as any)
        logic = sampleDataStateLogic()
        logic.mount()
    }

    it('shows the placeholder for a project that never ingested an event', async () => {
        mount({ ...MOCK_DEFAULT_TEAM, ingested_event: false })
        expect(logic.values.shouldShowSampleData).toBe(false)
        await expectLogic(dataWarehouseSetupLogic).toDispatchActions(['detectStatusSuccess'])
        await expectLogic(logic).toMatchValues({ shouldShowSampleData: true })
    })

    it.each(['external_data_sources', 'warehouse_tables'])(
        'hides samples when %s exist without events',
        async (resource) => {
            useMocks({
                get: { [`/api/environments/:team_id/${resource}/`]: { results: [{ id: 'example-resource' }] } },
            })
            mount({ ...MOCK_DEFAULT_TEAM, ingested_event: false })
            await expectLogic(dataWarehouseSetupLogic).toDispatchActions(['detectStatusSuccess'])
            expect(logic.values.shouldShowSampleData).toBe(false)
        }
    )

    it('does not claim the project is empty when warehouse detection fails', async () => {
        useMocks({ get: { '/api/environments/:team_id/warehouse_tables/': () => [503, {}] } })
        mount({ ...MOCK_DEFAULT_TEAM, ingested_event: false })
        await expectLogic(dataWarehouseSetupLogic).toDispatchActions(['detectStatusSuccess'])
        expect(logic.values.shouldShowSampleData).toBe(false)
    })

    it('hides the placeholder once a project has ingested', async () => {
        mount({ ...MOCK_DEFAULT_TEAM, ingested_event: true })
        await expectLogic(logic).toMatchValues({ shouldShowSampleData: false })
    })

    // Regression guard for the shared-dashboard placeholder bug: TeamPublicSerializer omits
    // `ingested_event`, so it reads as undefined on shared views. Without the isSharedView gate,
    // every empty tile on a real, data-carrying project falsely renders fake sample data.
    it('hides the placeholder on shared views even when ingested_event is absent', async () => {
        window.POSTHOG_EXPORTED_DATA = { type: ExportType.Embed }
        mount({ ...MOCK_DEFAULT_TEAM, ingested_event: undefined })
        await expectLogic(logic).toMatchValues({ shouldShowSampleData: false })
        expect(dataWarehouseSetupLogic.isMounted()).toBe(false)
    })
})
