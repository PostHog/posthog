import { router } from 'kea-router'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { catalogTablesLogic } from './catalogTablesLogic'
import { SECTION_VIEWED_EVENT, dataCatalogSceneLogic } from './dataCatalogSceneLogic'

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
                '/api/projects/:team_id/data_modeling_nodes/': { results: [], count: 0 },
                '/api/projects/:team_id/data_modeling_edges/': { results: [], count: 0 },
                '/api/projects/:team_id/warehouse_saved_queries/': { results: [], count: 0 },
            },
            post: {
                '/api/projects/:team_id/query/:query_kind/': { tables: {}, joins: [] },
            },
        })
        // Feature flags persist in local storage, so clear it to start each test with no flags.
        window.localStorage.clear()
        initKeaTests()
        tablesLogic = undefined
    })

    afterEach(() => {
        tablesLogic?.unmount()
        logic?.unmount()
        jest.restoreAllMocks()
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

    it.each([
        [true, 'usage'],
        [false, 'metrics'],
    ])(
        'opens a usage link that arrives before the flags only when the flag is on (flag on: %s)',
        async (flagOn, expectedTab) => {
            featureFlagLogic.actions.setFeatureFlags([], {})
            logic = dataCatalogSceneLogic()
            logic.mount()
            router.actions.push(urls.dataCatalog('usage'))
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.activeTab).toBe('metrics')

            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.DATA_CATALOG_USAGE], {
                [FEATURE_FLAGS.DATA_CATALOG_USAGE]: flagOn,
            })
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.activeTab).toBe(expectedTab)
        }
    )

    const RESTRUCTURE = [FEATURE_FLAGS.TODAY_RAIL_NAV, FEATURE_FLAGS.DATA_CATALOG_RESTRUCTURE]

    it.each([
        [
            'classic layout',
            false,
            [],
            ['/data-catalog', '/data-catalog?tab=relationships', '/data-catalog?tab=relationships&page=2'],
            [
                ['metrics', 'classic'],
                ['relationships', 'classic'],
            ],
        ],
        [
            'restructured layout',
            false,
            RESTRUCTURE,
            ['/data-catalog', '/data-catalog?tab=tables', '/data-catalog?tab=tables&filter=proposed'],
            [
                ['overview', 'restructured'],
                ['tables', 'restructured'],
            ],
        ],
        ['flags that arrive after the URL', true, RESTRUCTURE, ['/data-catalog'], [['overview', 'restructured']]],
    ])('reports each section view once, with its layout (%s)', async (_, flagsAfterMount, flags, paths, expected) => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation()
        const setFlags = (): void =>
            featureFlagLogic.actions.setFeatureFlags(flags, Object.fromEntries(flags.map((flag) => [flag, true])))
        if (!flagsAfterMount) {
            setFlags()
        }
        router.actions.push(paths[0])
        logic = dataCatalogSceneLogic()
        logic.mount()
        if (flagsAfterMount) {
            setFlags()
        }
        for (const path of paths.slice(1)) {
            router.actions.push(path)
        }
        await expectLogic(logic).toFinishAllListeners()

        const views = capture.mock.calls
            .filter(([event]) => event === SECTION_VIEWED_EVENT)
            .map(([, properties]) => [properties?.section, properties?.layout])
        expect(views).toEqual(expected)
    })
})
