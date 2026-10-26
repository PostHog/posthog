import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { clearAllCachedHasData } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

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

    it.each([
        ['/api/projects/:team_id/external_data_sources/exists/', { exists: true }],
        ['/api/projects/:team_id/warehouse_tables/', { results: [{ id: 'example-table' }] }],
    ])('hides samples when %s exist without events', async (resource, response) => {
        useMocks({
            get: { [resource as string]: response },
        })
        mount({ ...MOCK_DEFAULT_TEAM, ingested_event: false })
        await expectLogic(dataWarehouseSetupLogic).toDispatchActions(['detectStatusSuccess'])
        expect(logic.values.shouldShowSampleData).toBe(false)
    })

    it('does not claim the project is empty when warehouse detection fails', async () => {
        useMocks({ get: { '/api/projects/:team_id/warehouse_tables/': () => [503, {}] } })
        mount({ ...MOCK_DEFAULT_TEAM, ingested_event: false })
        await expectLogic(dataWarehouseSetupLogic).toDispatchActions(['detectStatusSuccess'])
        expect(logic.values.shouldShowSampleData).toBe(false)
    })

    it.each([{ ingested_event: true }, { ingested_event: false, is_demo: true }])(
        'does not start warehouse detection for an ineligible project (%j)',
        async (team) => {
            mount({ ...MOCK_DEFAULT_TEAM, ...team })
            await expectLogic(logic).toMatchValues({ shouldShowSampleData: false })
            expect(dataWarehouseSetupLogic.isMounted()).toBe(false)
        }
    )

    it('starts detection when the team loads and stops it after ingestion', async () => {
        mount(null)
        expect(dataWarehouseSetupLogic.isMounted()).toBe(false)
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, ingested_event: false })
        await expectLogic(dataWarehouseSetupLogic).toDispatchActions(['detectStatusSuccess'])
        expect(logic.values.shouldShowSampleData).toBe(true)
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, ingested_event: true })
        expect(dataWarehouseSetupLogic.isMounted()).toBe(false)
        expect(logic.values.shouldShowSampleData).toBe(false)
    })

    it('refreshes warehouse setup on navigation while the detector stays mounted', async () => {
        mount({ ...MOCK_DEFAULT_TEAM, ingested_event: false })
        await expectLogic(dataWarehouseSetupLogic).toDispatchActions(['detectStatusSuccess'])
        expect(logic.values.shouldShowSampleData).toBe(true)

        useMocks({ get: { '/api/projects/:team_id/external_data_sources/exists/': { exists: true } } })
        await expectLogic(dataWarehouseSetupLogic, () => router.actions.push(urls.sources()))
            .toFinishAllListeners()
            .toMatchValues({ setupStatus: 'has-data' })
        expect(logic.values.shouldShowSampleData).toBe(false)
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
