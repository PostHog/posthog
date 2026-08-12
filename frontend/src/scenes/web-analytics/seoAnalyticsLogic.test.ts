import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'
import { ExternalDataSource } from '~/types'

import { sourcesDataLogic } from 'products/data_warehouse/frontend/shared/logics/sourcesDataLogic'

import { TileId } from './common'
import { seoAnalyticsLogic } from './seoAnalyticsLogic'

const makeGscSource = (syncedSchemas: string[]): ExternalDataSource =>
    ({
        id: 'gsc-source-1',
        source_id: 'source-1',
        connection_id: 'conn-1',
        source_type: 'GoogleSearchConsole',
        status: 'Completed',
        prefix: '',
        schemas: [
            'search_analytics_by_date',
            'search_analytics_by_query',
            'search_analytics_by_page',
            'search_analytics_by_query_page',
        ].map((name) => ({
            id: `schema-${name}`,
            name,
            should_sync: syncedSchemas.includes(name),
            table: syncedSchemas.includes(name)
                ? { id: `table-${name}`, name: `googlesearchconsole_${name}` }
                : undefined,
        })),
    }) as unknown as ExternalDataSource

const mockSourcesResponse = (results: ExternalDataSource[]): void => {
    jest.spyOn(api.externalDataSources, 'list').mockResolvedValue({
        results,
        count: results.length,
        next: null,
        previous: null,
    })
}

describe('seoAnalyticsLogic', () => {
    let logic: ReturnType<typeof seoAnalyticsLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api.propertyDefinitions, 'list').mockResolvedValue({ results: [] } as any)
        jest.spyOn(api.hogFunctions, 'list').mockResolvedValue({ results: [] } as any)
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    const getTileTables = (
        tiles: ReturnType<typeof seoAnalyticsLogic.build>['values']['tiles']
    ): Partial<Record<TileId, string>> => {
        const tables: Partial<Record<TileId, string>> = {}
        for (const tile of tiles) {
            if (tile.kind === 'tabs') {
                const source = (tile.tabs[0].query as any).source
                tables[tile.tileId] = source.series[0].table_name
            } else if (tile.kind === 'query') {
                const match = ((tile.query as any).source.query as string).match(/FROM (\S+)/)
                tables[tile.tileId] = match?.[1]
            }
        }
        return tables
    }

    it('builds no tiles and reports no source when Google Search Console is not connected', async () => {
        mockSourcesResponse([])
        logic = seoAnalyticsLogic()
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(sourcesDataLogic, ['loadSources', 'loadSourcesSuccess'])
            .toMatchValues({
                hasGscSource: false,
                tiles: [],
            })
    })

    it.each([
        [
            'all schemas synced picks the preferred table per tile',
            [
                'search_analytics_by_date',
                'search_analytics_by_query',
                'search_analytics_by_page',
                'search_analytics_by_query_page',
            ],
            {
                [TileId.SEO_TRENDS]: 'googlesearchconsole_search_analytics_by_date',
                [TileId.SEO_QUERIES]: 'googlesearchconsole_search_analytics_by_query',
                [TileId.SEO_PAGES]: 'googlesearchconsole_search_analytics_by_page',
            },
        ],
        [
            'only the default schema synced falls back to it for every tile',
            ['search_analytics_by_query_page'],
            {
                [TileId.SEO_TRENDS]: 'googlesearchconsole_search_analytics_by_query_page',
                [TileId.SEO_QUERIES]: 'googlesearchconsole_search_analytics_by_query_page',
                [TileId.SEO_PAGES]: 'googlesearchconsole_search_analytics_by_query_page',
            },
        ],
    ])('%s', async (_name, syncedSchemas, expectedTables) => {
        mockSourcesResponse([makeGscSource(syncedSchemas)])
        logic = seoAnalyticsLogic()
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(sourcesDataLogic, ['loadSources', 'loadSourcesSuccess'])
            .toMatchValues({
                hasGscSource: true,
            })

        expect(getTileTables(logic.values.tiles)).toEqual(expectedTables)
    })

    it('builds no tiles when no search analytics schema is synced', async () => {
        mockSourcesResponse([makeGscSource([])])
        logic = seoAnalyticsLogic()
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(sourcesDataLogic, ['loadSources', 'loadSourcesSuccess'])
            .toMatchValues({
                hasGscSource: true,
                tiles: [],
            })
    })
})
