import { columnsFromResponse, getAutoVisualizationType } from '~/queries/nodes/DataVisualization/columnUtils'
import { getTableDisplayOptions } from '~/queries/nodes/DataVisualization/Components/tableDisplayOptions'
import { DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { cardVisualizationDisabledReason, withAxes } from './SqlVisualizationPicker'

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
        'all numeric, which the editor plots by promoting the first column to the x axis': {
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

    // The guard that stops this class of bug recurring: a card only offers what it can finish. Every
    // option is checked, so a chart type added later without a support classification fails here
    // rather than saving a query the tile has no settings to draw.
    it.each(Object.entries(responses))(
        'every type the card leaves enabled saves a query it can draw — %s',
        (_label, response) => {
            const columns = columnsFromResponse(response)
            const autoVisualizationType = getAutoVisualizationType(columns, response)
            const numericalColumns = columns.filter((column) => column.type.isNumerical)

            const options = getTableDisplayOptions(columns, numericalColumns, autoVisualizationType, (displayType) =>
                cardVisualizationDisabledReason(displayType, baseQuery, columns, autoVisualizationType)
            )

            const enabled = options
                .flatMap((group: any) => (Array.isArray(group.options) ? group.options : []))
                .filter((option: any) => !option.disabledReason)
                .map((option: any) => option.value as ChartDisplayType)

            expect(enabled.length).toBeGreaterThan(0)

            for (const displayType of enabled) {
                const saved = withAxes({ ...baseQuery, display: displayType }, columns, autoVisualizationType)
                const resolved =
                    displayType === ChartDisplayType.Auto ? autoVisualizationType : (displayType as ChartDisplayType)

                // A table and a big number draw without axes. Everything else the card offers must
                // come out with both, or the tile renders blank with no way to repair it.
                const needsAxes = ![ChartDisplayType.ActionsTable, ChartDisplayType.BoldNumber].includes(resolved)
                if (!needsAxes) {
                    continue
                }

                expect(saved.chartSettings?.xAxis?.column).toEqual(expect.any(String))
                expect(saved.chartSettings?.yAxis?.length ?? 0).toBeGreaterThan(0)
            }
        }
    )

    it('does not offer Auto when it resolves to a type the card cannot set up', () => {
        const response = responses['two strings and a numeric, which Auto resolves to a 2d heatmap']
        const columns = columnsFromResponse(response)
        const autoVisualizationType = getAutoVisualizationType(columns, response)

        expect(autoVisualizationType).toEqual(ChartDisplayType.TwoDimensionalHeatmap)
        expect(
            cardVisualizationDisabledReason(ChartDisplayType.Auto, baseQuery, columns, autoVisualizationType)
        ).toContain('Open the insight')
    })

    // The editor promotes the first numeric column to the x axis for an all-numeric result, so the
    // card has to offer what the editor can draw rather than refusing it.
    it('offers a line chart for an all-numeric result, as the editor does', () => {
        const response = responses['all numeric, which the editor plots by promoting the first column to the x axis']
        const columns = columnsFromResponse(response)
        const autoVisualizationType = getAutoVisualizationType(columns, response)

        expect(
            cardVisualizationDisabledReason(
                ChartDisplayType.ActionsLineGraph,
                baseQuery,
                columns,
                autoVisualizationType
            )
        ).toBeUndefined()

        const saved = withAxes(
            { ...baseQuery, display: ChartDisplayType.ActionsLineGraph },
            columns,
            autoVisualizationType
        )
        expect(saved.chartSettings?.xAxis?.column).toEqual('users')
        expect(saved.chartSettings?.yAxis).toEqual([{ column: 'events' }])
    })

    it('offers a chart type the insight already has axes for, even when the columns alone would not', () => {
        const response = responses['all string, so nothing is left to plot']
        const columns = columnsFromResponse(response)
        const autoVisualizationType = getAutoVisualizationType(columns, response)
        const alreadyAxed = {
            ...baseQuery,
            chartSettings: { xAxis: { column: 'country' }, yAxis: [{ column: 'browser' }] },
        } as DataVisualizationNode

        expect(
            cardVisualizationDisabledReason(ChartDisplayType.ActionsBar, baseQuery, columns, autoVisualizationType)
        ).toEqual('This insight has no numeric column to plot')
        expect(
            cardVisualizationDisabledReason(ChartDisplayType.ActionsBar, alreadyAxed, columns, autoVisualizationType)
        ).toBeUndefined()
    })

    it('leaves the table and the big number available whatever the columns are', () => {
        const response = responses['all string, so nothing is left to plot']
        const columns = columnsFromResponse(response)
        const autoVisualizationType = getAutoVisualizationType(columns, response)

        expect(
            cardVisualizationDisabledReason(ChartDisplayType.ActionsTable, baseQuery, columns, autoVisualizationType)
        ).toBeUndefined()
        expect(
            cardVisualizationDisabledReason(ChartDisplayType.BoldNumber, baseQuery, columns, autoVisualizationType)
        ).toBeUndefined()
    })
})
