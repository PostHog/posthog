import { expectLogic } from 'kea-test-utils'

import { DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { dataNodeLogic } from '../DataNode/dataNodeLogic'
import { columnsFromResponse } from './columnUtils'
import { DataVisualizationLogicProps, dataVisualizationLogic } from './dataVisualizationLogic'
import { applyVisualizationType } from './visualizationTypeSetup'

const testKey = 'test-visualization-type-setup'
const dataNodeCollectionId = 'new-test-setup'

const baseQuery: DataVisualizationNode = {
    kind: NodeKind.DataVisualizationNode,
    source: { kind: NodeKind.HogQLQuery, query: 'select 1' },
}

const responses = {
    'date and numeric': {
        columns: ['day', 'total'],
        types: [
            ['day', 'DateTime'],
            ['total', 'UInt64'],
        ],
        results: [
            ['2026-01-01', 1],
            ['2026-01-02', 2],
        ],
    },
    'all numeric': {
        columns: ['users', 'events'],
        types: [
            ['users', 'UInt64'],
            ['events', 'UInt64'],
        ],
        results: [
            [1, 2],
            [3, 4],
        ],
    },
    'two strings and a numeric': {
        columns: ['country', 'browser', 'hits'],
        types: [
            ['country', 'String'],
            ['browser', 'String'],
            ['hits', 'UInt64'],
        ],
        results: [['NL', 'Firefox', 3]],
    },
}

// The editor applies a picked chart type through kea actions, because it keeps axis state locally.
// A dashboard card renders its query read-only and has no such state, so it applies the same setup
// as a query change through applyVisualizationType. These tests hold the two together: if the
// editor's listener grows a step the shared function does not have, the pair stops matching here
// rather than on someone's dashboard.
describe('applyVisualizationType matches what the editor produces', () => {
    let logic: ReturnType<typeof dataVisualizationLogic.build>

    // The initial load settles first, otherwise its empty result overwrites the one set here.
    const mountWith = async (response: Record<string, any>): Promise<void> => {
        logic = dataVisualizationLogic({
            key: testKey,
            query: baseQuery,
            dataNodeCollectionId,
        } as DataVisualizationLogicProps)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        dataNodeLogic({ key: testKey, query: baseQuery.source, dataNodeCollectionId }).actions.setResponse(response)
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it.each([
        {
            label: 'a line chart on a date and a numeric',
            response: 'date and numeric',
            type: ChartDisplayType.ActionsLineGraph,
        },
        {
            label: 'a line chart on an all-numeric result',
            response: 'all numeric',
            type: ChartDisplayType.ActionsLineGraph,
        },
        {
            label: 'an area chart on an all-numeric result',
            response: 'all numeric',
            type: ChartDisplayType.ActionsAreaGraph,
        },
        { label: 'a pie chart', response: 'date and numeric', type: ChartDisplayType.ActionsPie },
        { label: 'a scatter plot', response: 'all numeric', type: ChartDisplayType.ScatterPlot },
        { label: 'a 2d heatmap', response: 'two strings and a numeric', type: ChartDisplayType.TwoDimensionalHeatmap },
        { label: 'a bar chart', response: 'date and numeric', type: ChartDisplayType.ActionsBar },
        { label: 'a table', response: 'date and numeric', type: ChartDisplayType.ActionsTable },
    ])('$label', async ({ response: responseKey, type }) => {
        const response = responses[responseKey as keyof typeof responses]
        await mountWith(response)

        // What the editor arrives at, as the query it would save.
        const before = logic.values.query
        logic.actions.setVisualizationType(type)
        await expectLogic(logic).toFinishAllListeners()
        const fromEditor = logic.values.query

        // What a card would save for the same pick, starting from the same query.
        const fromCard = applyVisualizationType(before, type, columnsFromResponse(response), response.results.length)

        expect(fromCard.display).toEqual(fromEditor.display)
        expect(fromCard.chartSettings?.xAxis).toEqual(fromEditor.chartSettings?.xAxis)
        expect(fromCard.chartSettings?.yAxis).toEqual(fromEditor.chartSettings?.yAxis)
        expect(fromCard.chartSettings?.pie?.sliceContent).toEqual(fromEditor.chartSettings?.pie?.sliceContent)
        expect(fromCard.chartSettings?.heatmap).toEqual(fromEditor.chartSettings?.heatmap)
    })

    // The cases above all start from a query with no chartSettings, which is the one shape that
    // cannot diverge. These start from a query that already carries axes, including the emptied
    // yAxis the editor writes when a user deletes every series.
    it.each([
        {
            label: 'a query whose y series were all deleted',
            chartSettings: { yAxis: [] },
            response: 'date and numeric',
            type: ChartDisplayType.ActionsBar,
        },
        {
            label: 'a query with axes already chosen',
            chartSettings: { xAxis: { column: 'total' }, yAxis: [{ column: 'day' }] },
            response: 'date and numeric',
            type: ChartDisplayType.ActionsLineGraph,
        },
        {
            label: 'a query with only an x axis set',
            chartSettings: { xAxis: { column: 'day' } },
            response: 'date and numeric',
            type: ChartDisplayType.ActionsBar,
        },
    ])('$label', async ({ chartSettings, response: responseKey, type }) => {
        const response = responses[responseKey as keyof typeof responses]
        const seeded = { ...baseQuery, chartSettings } as DataVisualizationNode

        logic = dataVisualizationLogic({
            key: testKey,
            query: seeded,
            dataNodeCollectionId,
        } as DataVisualizationLogicProps)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        dataNodeLogic({ key: testKey, query: baseQuery.source, dataNodeCollectionId }).actions.setResponse(response)
        await expectLogic(logic).toFinishAllListeners()

        const before = logic.values.query
        logic.actions.setVisualizationType(type)
        await expectLogic(logic).toFinishAllListeners()
        const fromEditor = logic.values.query

        const fromCard = applyVisualizationType(before, type, columnsFromResponse(response), response.results.length)

        expect(fromCard.chartSettings?.xAxis).toEqual(fromEditor.chartSettings?.xAxis)
        expect(fromCard.chartSettings?.yAxis).toEqual(fromEditor.chartSettings?.yAxis)
    })
})
