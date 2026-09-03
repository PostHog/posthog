import { getTableDisplayOptions } from '~/queries/nodes/DataVisualization/Components/TableDisplay'
import {
    applyVisualizationType,
    columnsFromResponse,
    getAutoVisualizationType,
} from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { sqlVisualizationDisabledReason } from '~/queries/nodes/DataVisualization/sqlVisualizationSupport'
import { DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

describe('dashboard SQL visualization support', () => {
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

    it.each(Object.entries(responses))(
        'every type the card leaves enabled saves a query it can draw: %s',
        (_label, response) => {
            const columns = columnsFromResponse(response)
            const autoVisualizationType = getAutoVisualizationType(columns, response.result.length)
            const numericalColumns = columns.filter((column) => column.type.isNumerical)

            const options = getTableDisplayOptions(columns, numericalColumns, autoVisualizationType, (displayType) =>
                sqlVisualizationDisabledReason(
                    displayType,
                    baseQuery,
                    columns,
                    response.result.length,
                    autoVisualizationType
                )
            )

            const enabled = options
                .flatMap((group: any) => (Array.isArray(group.options) ? group.options : []))
                .filter((option: any) => !option.disabledReason)
                .map((option: any) => option.value as ChartDisplayType)

            expect(enabled.length).toBeGreaterThan(0)

            for (const displayType of enabled) {
                const saved = applyVisualizationType(baseQuery, displayType, columns, response.result.length)
                const resolved =
                    displayType === ChartDisplayType.Auto ? autoVisualizationType : (displayType as ChartDisplayType)

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
        const autoVisualizationType = getAutoVisualizationType(columns, response.result.length)

        expect(autoVisualizationType).toEqual(ChartDisplayType.TwoDimensionalHeatmap)
        expect(
            sqlVisualizationDisabledReason(
                ChartDisplayType.Auto,
                baseQuery,
                columns,
                response.result.length,
                autoVisualizationType
            )
        ).toContain('Open the insight')
    })

    it('does not treat stale saved axes as making a chart type available', () => {
        const response = responses['all string, so nothing is left to plot']
        const columns = columnsFromResponse(response)
        const autoVisualizationType = getAutoVisualizationType(columns, response.result.length)
        const staleAxes = {
            ...baseQuery,
            chartSettings: { xAxis: { column: 'country' }, yAxis: [{ column: 'browser' }] },
        } as DataVisualizationNode

        for (const candidate of [baseQuery, staleAxes]) {
            expect(
                sqlVisualizationDisabledReason(
                    ChartDisplayType.ActionsBar,
                    candidate,
                    columns,
                    response.result.length,
                    autoVisualizationType
                )
            ).toEqual('This insight has no numeric column to plot')
        }
    })

    it('preserves saved axes while response columns are unavailable', () => {
        const query = {
            ...baseQuery,
            chartSettings: {
                xAxis: { column: 'day' },
                yAxis: [
                    {
                        column: 'total',
                        settings: { formatting: { prefix: '$', suffix: '' } },
                    },
                ],
            },
        } as DataVisualizationNode

        expect(applyVisualizationType(query, ChartDisplayType.ActionsBar, [], 0).chartSettings).toEqual(
            query.chartSettings
        )
    })
})
