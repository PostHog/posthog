import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { catalogTablesLogic } from './catalogTablesLogic'
import { dataCatalogSceneLogic } from './dataCatalogSceneLogic'

describe('dataCatalogSceneLogic', () => {
    let logic: ReturnType<typeof dataCatalogSceneLogic.build>
    let tablesLogic: ReturnType<typeof catalogTablesLogic.build> | undefined

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/data_quality_checks/': { results: [], count: 0 },
                '/api/projects/:team_id/data_quality_checks/health/': [],
                '/api/projects/:team_id/data_quality_checks/schedules/': [],
                '/api/projects/:team_id/data_quality_checks/subjects/': [],
                '/api/projects/:team_id/data_catalog/certifications/': { results: [], count: 0 },
                '/api/environments/:team_id/data_modeling_nodes/': { results: [], count: 0 },
                '/api/environments/:team_id/data_modeling_edges/': { results: [], count: 0 },
                '/api/environments/:team_id/warehouse_saved_queries/': { results: [], count: 0 },
            },
            post: {
                '/api/environments/:team_id/query/:query_kind/': { tables: {}, joins: [] },
            },
        })
        initKeaTests()
        tablesLogic = undefined
    })

    afterEach(() => {
        tablesLogic?.unmount()
        logic?.unmount()
    })

    it('keeps the certifications tab when the catalog restructure is off', async () => {
        router.actions.push('/data-catalog?tab=certifications')
        logic = dataCatalogSceneLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.activeTab).toEqual('certifications')
    })

    it.each([
        ['/data-catalog?tab=certifications', 'proposed', ''],
        ['/data-catalog?tab=certifications&table=orders', 'any', 'orders'],
        ['/data-catalog?tab=tables&filter=proposed', 'proposed', ''],
    ])('the Tables tab opened from %s shows the %s trust filter', async (path, expectedTrust, expectedSearch) => {
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.TODAY_RAIL_NAV]: true,
            [FEATURE_FLAGS.DATA_CATALOG_RESTRUCTURE]: true,
        })
        router.actions.push(path)
        logic = dataCatalogSceneLogic()
        logic.mount()

        tablesLogic = catalogTablesLogic()
        tablesLogic.mount()
        await expectLogic(tablesLogic).toFinishAllListeners()

        expect(logic.values.activeTab).toEqual('tables')
        expect(tablesLogic.values.filters.trust).toEqual(expectedTrust)
        expect(tablesLogic.values.search).toEqual(expectedSearch)
        expect(router.values.searchParams).toEqual({ tab: 'tables' })
    })
})
