import { expectLogic } from 'kea-test-utils'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { dataNodeLogic } from '../../DataNode/dataNodeLogic'
import { DataVisualizationLogicProps, dataVisualizationLogic } from '../dataVisualizationLogic'
import { seriesBreakdownLogic } from './seriesBreakdownLogic'

const testUniqueKey = 'testUniqueKey'

const initialQuery: DataVisualizationNode = {
    kind: NodeKind.DataVisualizationNode,
    source: {
        kind: NodeKind.HogQLQuery,
        query: `select event, properties.$browser as browser, count() as total_count from events group by 1, 2`,
    },
    tableSettings: {
        columns: [
            {
                column: 'event',
                settings: {
                    formatting: {
                        prefix: '',
                        suffix: '',
                    },
                },
            },
            {
                column: 'browser',
                settings: {
                    formatting: {
                        prefix: '',
                        suffix: '',
                    },
                },
            },
            {
                column: 'total_count',
                settings: {
                    formatting: {
                        prefix: '',
                        suffix: '',
                    },
                },
            },
        ],
        conditionalFormatting: [],
    },
    chartSettings: { goalLines: undefined },
}

// globalQuery represents the query object that is passed into the data
// visualization logic and series breakdown logic it is modified by calls to
// setQuery so we want to ensure this is updated correctly
let globalQuery: DataVisualizationNode = { ...initialQuery }

const dummyDataVisualizationLogicProps: DataVisualizationLogicProps = {
    key: testUniqueKey,
    query: globalQuery,
    setQuery: (setter) => {
        globalQuery = setter(globalQuery)
        dummyDataVisualizationLogicProps.query = globalQuery
        dataVisualizationLogic.build(dummyDataVisualizationLogicProps)
    },
    editMode: false,
    dataNodeCollectionId: 'new-test-SQL',
}

describe('seriesBreakdownLogic', () => {
    let logic: ReturnType<typeof seriesBreakdownLogic.build>
    let builtDataVizLogic: ReturnType<typeof dataVisualizationLogic.build>

    beforeEach(() => {
        initKeaTests()

        // Mock prefersColorSchemeMedia to avoid TypeError
        // (this is a known issue with jest and window.matchMedia)
        // and is used by themeLogic
        Object.defineProperty(window, 'matchMedia', {
            writable: true,
            value: jest.fn().mockImplementation((query) => ({
                matches: false,
                media: query,
                onchange: null,
                addEventListener: jest.fn(),
                removeEventListener: jest.fn(),
                addListener: jest.fn(), // deprecated
                removeListener: jest.fn(), // deprecated
                dispatchEvent: jest.fn(),
            })),
        })

        featureFlagLogic.mount()

        // ensure we reset the globalQuery state before each test
        globalQuery = { ...initialQuery }

        builtDataVizLogic = dataVisualizationLogic(dummyDataVisualizationLogicProps)
        builtDataVizLogic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        builtDataVizLogic?.unmount()
    })

    it('sets the correct values after mounting', async () => {
        logic = seriesBreakdownLogic({ key: testUniqueKey })
        logic.mount()

        await expectLogic(logic).toMatchValues({
            showSeriesBreakdown: false,
            selectedSeriesBreakdownColumn: undefined,
        })

        expect(globalQuery).toEqual({
            ...initialQuery,
            chartSettings: {
                goalLines: undefined,
                seriesBreakdownColumn: undefined,
            },
        })
    })

    // this was an example of a previous bug where the series breakdown logic
    // would mount and override the existing query settings
    it('does not override existing query settings after mounting', async () => {
        // set visualization type to line graph and ensure this persists
        builtDataVizLogic.actions.setVisualizationType(ChartDisplayType.ActionsLineGraph)
        expect(globalQuery.display).toEqual(ChartDisplayType.ActionsLineGraph)

        logic = seriesBreakdownLogic({ key: testUniqueKey })
        logic.mount()

        await expectLogic(logic).toMatchValues({
            showSeriesBreakdown: false,
            selectedSeriesBreakdownColumn: undefined,
        })

        expect(globalQuery).toEqual({
            ...initialQuery,
            chartSettings: {
                goalLines: undefined,
                seriesBreakdownColumn: undefined,
            },
            display: ChartDisplayType.ActionsLineGraph,
        })
    })

    it('adds a series breakdown', async () => {
        logic = seriesBreakdownLogic({ key: testUniqueKey })
        logic.mount()

        logic.actions.addSeriesBreakdown('test_column')
        await expectLogic(logic).toMatchValues({
            showSeriesBreakdown: true,
            selectedSeriesBreakdownColumn: 'test_column',
        })

        expect(globalQuery).toEqual({
            ...initialQuery,
            chartSettings: {
                goalLines: undefined,
                seriesBreakdownColumn: 'test_column',
            },
        })
    })

    it('adds a series breakdown after mount if one already selected in query', async () => {
        builtDataVizLogic.actions.setQuery((query) => ({
            ...query,
            chartSettings: {
                goalLines: undefined,
                seriesBreakdownColumn: 'test_column',
            },
        }))

        logic = seriesBreakdownLogic({ key: testUniqueKey })
        logic.mount()

        await expectLogic(logic).toMatchValues({
            selectedSeriesBreakdownColumn: 'test_column',
            showSeriesBreakdown: true,
        })

        expect(globalQuery).toEqual({
            ...initialQuery,
            chartSettings: {
                goalLines: undefined,
                seriesBreakdownColumn: 'test_column',
            },
        })
    })

    it('deletes a series breakdown', async () => {
        logic = seriesBreakdownLogic({ key: testUniqueKey })
        logic.mount()

        logic.actions.addSeriesBreakdown('test_column')

        logic.actions.deleteSeriesBreakdown()
        await expectLogic(logic).toMatchValues({
            showSeriesBreakdown: false,
            selectedSeriesBreakdownColumn: undefined,
        })

        expect(globalQuery).toEqual({
            ...initialQuery,
            chartSettings: {
                goalLines: undefined,
                seriesBreakdownColumn: undefined,
            },
        })
    })

    it('deletes a series breakdown when clearAxis is called', async () => {
        logic = seriesBreakdownLogic({ key: testUniqueKey })
        logic.mount()

        logic.actions.addSeriesBreakdown('test_column')

        logic.actions.clearAxis()
        await expectLogic(logic).toMatchValues({
            showSeriesBreakdown: false,
            selectedSeriesBreakdownColumn: undefined,
        })

        expect(globalQuery).toEqual({
            ...initialQuery,
            tableSettings: {
                columns: [],
                conditionalFormatting: [],
            },
            chartSettings: {
                goalLines: undefined,
                seriesBreakdownColumn: undefined,
                xAxis: undefined,
                yAxis: [],
            },
        })
    })

    it('computes the correct data', async () => {
        logic = seriesBreakdownLogic({ key: testUniqueKey })
        logic.mount()

        const builtDataNodeLogic = dataNodeLogic({
            key: testUniqueKey,
            query: globalQuery.source,
        })
        builtDataNodeLogic.mount()
        builtDataNodeLogic.actions.setResponse({
            results: [
                ['signed_up', 'Safari', 11],
                ['signed_up', 'Firefox', 22],
                ['signed_up', 'Chrome', 59],
                ['logged_out', 'Safari', 32],
                ['downloaded_file', 'Firefox', 820],
                ['logged_out', 'Chrome', 173],
                ['downloaded_file', 'Chrome', 2218],
                ['downloaded_file', 'Safari', 282],
                ['logged_out', 'Firefox', 60],
            ],
            columns: ['event', 'browser', 'total_count'],
            types: [
                ['event', 'String'],
                ['browser', 'Nullable(String)'],
                ['total_count', 'UInt64'],
            ],
        })

        builtDataVizLogic.actions.updateXSeries('event')

        logic.actions.addSeriesBreakdown('browser')

        await expectLogic(logic).toMatchValues({
            breakdownColumnValues: ['Safari', 'Firefox', 'Chrome'],
            seriesBreakdownData: {
                xData: {
                    column: {
                        name: 'event',
                        type: { name: 'STRING', isNumerical: false },
                        label: 'event - String',
                        dataIndex: 0,
                    },
                    data: ['signed_up', 'logged_out', 'downloaded_file'],
                },
                seriesData: [
                    {
                        name: 'Safari',
                        data: [11, 32, 282],
                        settings: {
                            formatting: { prefix: '', suffix: '' },
                            display: { displayType: undefined, yAxisPosition: undefined },
                        },
                    },
                    {
                        name: 'Firefox',
                        data: [22, 60, 820],
                        settings: {
                            formatting: { prefix: '', suffix: '' },
                            display: { displayType: undefined, yAxisPosition: undefined },
                        },
                    },
                    {
                        name: 'Chrome',
                        data: [59, 173, 2218],
                        settings: {
                            formatting: { prefix: '', suffix: '' },
                            display: { displayType: undefined, yAxisPosition: undefined },
                        },
                    },
                ],
                isUnaggregated: false,
            },
        })
    })
})
