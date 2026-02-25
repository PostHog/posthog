import { expectLogic } from 'kea-test-utils'

import { DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { dataNodeLogic } from '../DataNode/dataNodeLogic'
import { DataVisualizationLogicProps, dataVisualizationLogic } from './dataVisualizationLogic'

const testKey = 'test-auto-visualization'
const dataNodeCollectionId = 'new-test-SQL'

const defaultQuery: DataVisualizationNode = {
    kind: NodeKind.DataVisualizationNode,
    source: {
        kind: NodeKind.HogQLQuery,
        query: 'select 1',
    },
    display: ChartDisplayType.Auto,
}

describe('dataVisualizationLogic', () => {
    let logic: ReturnType<typeof dataVisualizationLogic.build>

    beforeEach(() => {
        initKeaTests()

        logic = dataVisualizationLogic({
            key: testKey,
            query: defaultQuery,
            dataNodeCollectionId,
        } as DataVisualizationLogicProps)
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    test.each([
        {
            name: 'shows a big number for a single numeric column',
            response: {
                columns: ['value'],
                types: [['value', 'Int64']],
                results: [[1]],
            },
            expected: ChartDisplayType.BoldNumber,
        },
        {
            name: 'shows a line chart when a timestamp column is present',
            response: {
                columns: ['timestamp', 'value'],
                types: [
                    ['timestamp', 'DateTime'],
                    ['value', 'Int64'],
                ],
                results: [
                    ['2025-01-01 00:00:00', 1],
                    ['2025-01-02 00:00:00', 2],
                ],
            },
            expected: ChartDisplayType.ActionsLineGraph,
        },
        {
            name: 'shows a bar chart when only one timeseries point is present',
            response: {
                columns: ['timestamp', 'value'],
                types: [
                    ['timestamp', 'DateTime'],
                    ['value', 'Int64'],
                ],
                results: [['2025-01-01 00:00:00', 1]],
            },
            expected: ChartDisplayType.ActionsBar,
        },
        {
            name: 'shows a 2d heatmap for two string columns and one numeric column',
            response: {
                columns: ['region', 'segment', 'count'],
                types: [
                    ['region', 'String'],
                    ['segment', 'String'],
                    ['count', 'Int64'],
                ],
                results: [['US', 'Enterprise', 10]],
            },
            expected: ChartDisplayType.TwoDimensionalHeatmap,
        },
        {
            name: 'shows a bar chart for non-time-series numeric data',
            response: {
                columns: ['group', 'value'],
                types: [
                    ['group', 'String'],
                    ['value', 'Int64'],
                ],
                results: [['A', 1]],
            },
            expected: ChartDisplayType.ActionsBar,
        },
    ])('$name', async ({ response, expected }) => {
        dataNodeLogic({ key: testKey, query: defaultQuery.source, dataNodeCollectionId }).actions.setResponse(response)

        await expectLogic(logic).toMatchValues({
            effectiveVisualizationType: expected,
        })
    })

    it('auto-selects the first non-y-axis column as x-axis for bar charts', async () => {
        dataNodeLogic({ key: testKey, query: defaultQuery.source, dataNodeCollectionId }).actions.setResponse({
            columns: ['fruit', 'count'],
            types: [
                ['fruit', 'String'],
                ['count', 'Int64'],
            ],
            results: [
                ['banana', 1],
                ['pineapple', 2],
            ],
        })

        await expectLogic(logic).toMatchValues({
            selectedXAxis: 'fruit',
            selectedYAxis: [
                {
                    name: 'count',
                    settings: {
                        formatting: {
                            prefix: '',
                            suffix: '',
                        },
                    },
                },
            ],
        })
    })

    it('resets axes when y-axis columns are no longer numerical', async () => {
        const dataNode = dataNodeLogic({ key: testKey, query: defaultQuery.source, dataNodeCollectionId })

        dataNode.actions.setResponse({
            columns: ['1', '2', '3'],
            types: [
                ['1', 'Int64'],
                ['2', 'Int64'],
                ['3', 'Int64'],
            ],
            results: [[1, 2, 3]],
        })

        await expectLogic(logic).toMatchValues({
            selectedXAxis: null,
            selectedYAxis: [
                {
                    name: '1',
                    settings: {
                        formatting: {
                            prefix: '',
                            suffix: '',
                        },
                    },
                },
                {
                    name: '2',
                    settings: {
                        formatting: {
                            prefix: '',
                            suffix: '',
                        },
                    },
                },
                {
                    name: '3',
                    settings: {
                        formatting: {
                            prefix: '',
                            suffix: '',
                        },
                    },
                },
            ],
        })

        dataNode.actions.setResponse({
            columns: ['1', '2', '3'],
            types: [
                ['1', 'String'],
                ['2', 'Int64'],
                ['3', 'String'],
            ],
            results: [['a', 2, 'b']],
        })

        await expectLogic(logic).toMatchValues({
            selectedXAxis: '1',
            selectedYAxis: [
                {
                    name: '2',
                    settings: {
                        formatting: {
                            prefix: '',
                            suffix: '',
                        },
                    },
                },
            ],
        })
    })

    it('does not resolve to a time-series chart without a date column', async () => {
        logic.actions.setVisualizationType(ChartDisplayType.ActionsLineGraph)

        dataNodeLogic({ key: testKey, query: defaultQuery.source, dataNodeCollectionId }).actions.setResponse({
            columns: ['first_value', 'second_value'],
            types: [
                ['first_value', 'Int64'],
                ['second_value', 'Int64'],
            ],
            results: [[1, 2]],
        })

        await expectLogic(logic).toMatchValues({
            effectiveVisualizationType: ChartDisplayType.ActionsLineGraph,
        })
    })

    it('fills x-axis labels with empty values when no x-axis is selected', async () => {
        dataNodeLogic({ key: testKey, query: defaultQuery.source, dataNodeCollectionId }).actions.setResponse({
            columns: ['first_value', 'second_value', 'third_value'],
            types: [
                ['first_value', 'Int64'],
                ['second_value', 'Int64'],
                ['third_value', 'Int64'],
            ],
            results: [
                [1, 2, 3],
                [4, 5, 6],
            ],
        })

        logic.actions.clearAxis()

        await expectLogic(logic).toMatchValues({
            xData: {
                column: {
                    name: 'None',
                    type: {
                        name: 'STRING',
                        isNumerical: false,
                    },
                    label: 'None',
                    dataIndex: -1,
                },
                data: ['', ''],
            },
        })
    })

    it('does not resolve to a time-series chart when there is only one row', async () => {
        logic.actions.setVisualizationType(ChartDisplayType.ActionsLineGraph)

        dataNodeLogic({ key: testKey, query: defaultQuery.source, dataNodeCollectionId }).actions.setResponse({
            columns: ['timestamp', 'value'],
            types: [
                ['timestamp', 'DateTime'],
                ['value', 'Int64'],
            ],
            results: [['2025-01-01 00:00:00', 1]],
        })

        await expectLogic(logic).toMatchValues({
            effectiveVisualizationType: ChartDisplayType.ActionsLineGraph,
        })
    })

    it('respects explicit line chart display even when auto would choose heatmap', async () => {
        logic.actions.setVisualizationType(ChartDisplayType.ActionsLineGraph)

        dataNodeLogic({ key: testKey, query: defaultQuery.source, dataNodeCollectionId }).actions.setResponse({
            columns: ['bucket', 'flag_state', 'reverse_proxy'],
            types: [
                ['bucket', 'String'],
                ['flag_state', 'String'],
                ['reverse_proxy', 'Float64'],
            ],
            results: [['2025-01-01', 'control', 0.2]],
        })

        await expectLogic(logic).toMatchValues({
            autoVisualizationType: ChartDisplayType.TwoDimensionalHeatmap,
            effectiveVisualizationType: ChartDisplayType.ActionsLineGraph,
        })
    })

    it('auto-fills 2d heatmap columns when auto resolves to heatmap', async () => {
        logic.actions.toggleChartSettingsPanel(true)

        dataNodeLogic({ key: testKey, query: defaultQuery.source, dataNodeCollectionId }).actions.setResponse({
            columns: ['region', 'segment', 'count'],
            types: [
                ['region', 'String'],
                ['segment', 'String'],
                ['count', 'Int64'],
            ],
            results: [['US', 'Enterprise', 10]],
        })

        await expectLogic(logic).toMatchValues({
            effectiveVisualizationType: ChartDisplayType.TwoDimensionalHeatmap,
            chartSettings: {
                heatmap: {
                    xAxisColumn: 'region',
                    yAxisColumn: 'segment',
                    valueColumn: 'count',
                },
            },
        })
    })
    it('auto-fills 2d heatmap columns when selecting auto on heatmap data', async () => {
        dataNodeLogic({ key: testKey, query: defaultQuery.source, dataNodeCollectionId }).actions.setResponse({
            columns: ['region', 'segment', 'count'],
            types: [
                ['region', 'String'],
                ['segment', 'String'],
                ['count', 'Int64'],
            ],
            results: [['US', 'Enterprise', 10]],
        })

        logic.actions.setVisualizationType(ChartDisplayType.ActionsBar)
        logic.actions.setVisualizationType(ChartDisplayType.Auto)

        await expectLogic(logic).toMatchValues({
            visualizationType: ChartDisplayType.Auto,
            effectiveVisualizationType: ChartDisplayType.TwoDimensionalHeatmap,
            chartSettings: {
                heatmap: {
                    xAxisColumn: 'region',
                    yAxisColumn: 'segment',
                    valueColumn: 'count',
                },
            },
        })
    })
})
