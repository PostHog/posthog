import { columnsFromResponse, getAutoVisualizationType } from '~/queries/nodes/DataVisualization/columnUtils'
import { getTableDisplayOptions } from '~/queries/nodes/DataVisualization/Components/tableDisplayOptions'
import { DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { AXIS_PLOTTING_TYPES, cardVisualizationDisabledReason, withAxes } from './SqlVisualizationPicker'

describe('SqlVisualizationPicker support rules', () => {
    const responses = {
        'date and numeric': {
            columns: ['day', 'total'],
            types: [
                ['day', 'DateTime'],
                ['total', 'UInt64'],
            ],
            result: [
                ['2026-01-01', 1],
                ['2026-01-02', 2],
            ],
        },
        'two strings and a numeric, which Auto resolves to a 2d heatmap': {
            columns: ['country', 'browser', 'hits'],
            types: [
                ['country', 'String'],
                ['browser', 'String'],
                ['hits', 'UInt64'],
            ],
            result: [['NL', 'Firefox', 3]],
        },
        'all numeric, so no column is left for the x axis': {
            columns: ['users', 'events'],
            types: [
                ['users', 'UInt64'],
                ['events', 'UInt64'],
            ],
            result: [[1, 2]],
        },
        'all string, so nothing is left to plot': {
            columns: ['country', 'browser'],
            types: [
                ['country', 'String'],
                ['browser', 'String'],
            ],
            result: [['NL', 'Firefox']],
        },
        'a single numeric column': {
            columns: ['total'],
            types: [['total', 'UInt64']],
            result: [[7]],
        },
    }

    const baseQuery = {
        kind: NodeKind.DataVisualizationNode,
        source: { kind: NodeKind.HogQLQuery, query: 'select 1' },
    } as DataVisualizationNode

    // The guard that stops this class of bug recurring: a card only offers what it can finish. If an
    // enabled type ends up saved without the axes it draws from, the tile renders blank and the
    // dashboard has no control to repair it.
    it.each(Object.entries(responses))(
        'every type the card leaves enabled saves a query it can draw — %s',
        (_label, response) => {
            const columns = columnsFromResponse(response)
            const autoVisualizationType = getAutoVisualizationType(columns, response)
            const numericalColumns = columns.filter((column) => column.type.isNumerical)

            const options = getTableDisplayOptions(columns, numericalColumns, autoVisualizationType, (displayType) =>
                cardVisualizationDisabledReason(displayType, columns, autoVisualizationType)
            )

            const enabled = options
                .flatMap((group: any) => (Array.isArray(group.options) ? group.options : []))
                .filter((option: any) => !option.disabledReason)
                .map((option: any) => option.value as ChartDisplayType)

            expect(enabled.length).toBeGreaterThan(0)

            for (const displayType of enabled) {
                const saved = withAxes({ ...baseQuery, display: displayType }, columns, autoVisualizationType)
                const drawnAs =
                    displayType === ChartDisplayType.Auto ? autoVisualizationType : (displayType as ChartDisplayType)

                if (!AXIS_PLOTTING_TYPES.includes(drawnAs)) {
                    continue
                }

                // An enabled axis-plotting type must come out with both axes filled. Anything less
                // draws a blank tile the dashboard cannot repair.
                expect({
                    displayType,
                    drawnAs,
                    xAxis: saved.chartSettings?.xAxis?.column,
                    yAxisCount: saved.chartSettings?.yAxis?.length ?? 0,
                }).toMatchObject({
                    xAxis: expect.any(String),
                    yAxisCount: expect.any(Number),
                })
                expect(saved.chartSettings?.yAxis?.length ?? 0).toBeGreaterThan(0)
            }
        }
    )

    it('does not offer Auto when it resolves to a type the card cannot set up', () => {
        const response = responses['two strings and a numeric, which Auto resolves to a 2d heatmap']
        const columns = columnsFromResponse(response)
        const autoVisualizationType = getAutoVisualizationType(columns, response)

        expect(autoVisualizationType).toEqual(ChartDisplayType.TwoDimensionalHeatmap)
        expect(cardVisualizationDisabledReason(ChartDisplayType.Auto, columns, autoVisualizationType)).toContain(
            'Open the insight'
        )
    })

    it('does not offer a bar chart when no column can fill the x axis', () => {
        const response = responses['all numeric, so no column is left for the x axis']
        const columns = columnsFromResponse(response)
        const autoVisualizationType = getAutoVisualizationType(columns, response)

        expect(cardVisualizationDisabledReason(ChartDisplayType.ActionsBar, columns, autoVisualizationType)).toEqual(
            'This insight has no numeric column to plot'
        )
    })

    it('leaves the table and the big number available whatever the columns are', () => {
        const response = responses['all string, so nothing is left to plot']
        const columns = columnsFromResponse(response)
        const autoVisualizationType = getAutoVisualizationType(columns, response)

        expect(
            cardVisualizationDisabledReason(ChartDisplayType.ActionsTable, columns, autoVisualizationType)
        ).toBeUndefined()
        expect(
            cardVisualizationDisabledReason(ChartDisplayType.BoldNumber, columns, autoVisualizationType)
        ).toBeUndefined()
    })
})
