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
            effectiveVisualizationType: ChartDisplayType.ActionsBar,
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
            effectiveVisualizationType: ChartDisplayType.ActionsBar,
        })
    })
})
