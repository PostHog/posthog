import { useValues } from 'kea'

import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { insightLogic } from 'scenes/insights/insightLogic'

import { BoxPlotDatum } from '~/queries/schema/schema-general'

import { boxPlotChartLogic } from './boxPlotChartLogic'

export function BoxPlotResultsTable(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { boxplotData, trendsFilter } = useValues(boxPlotChartLogic(insightProps))

    if (!boxplotData || boxplotData.length === 0) {
        return null
    }

    const formatValue = (value: number): string => formatAggregationAxisValue(trendsFilter, value)

    return (
        <LemonTable
            dataSource={boxplotData}
            columns={[
                {
                    title: 'Date',
                    key: 'label',
                    render: (_, datum: BoxPlotDatum) => datum.label,
                },
                {
                    title: 'Min',
                    key: 'min',
                    align: 'right',
                    render: (_, datum: BoxPlotDatum) => formatValue(datum.min),
                },
                {
                    title: '25th percentile',
                    key: 'p25',
                    align: 'right',
                    render: (_, datum: BoxPlotDatum) => formatValue(datum.p25),
                },
                {
                    title: 'Median',
                    key: 'median',
                    align: 'right',
                    render: (_, datum: BoxPlotDatum) => formatValue(datum.median),
                },
                {
                    title: 'Mean',
                    key: 'mean',
                    align: 'right',
                    render: (_, datum: BoxPlotDatum) => formatValue(datum.mean),
                },
                {
                    title: '75th percentile',
                    key: 'p75',
                    align: 'right',
                    render: (_, datum: BoxPlotDatum) => formatValue(datum.p75),
                },
                {
                    title: 'Max',
                    key: 'max',
                    align: 'right',
                    render: (_, datum: BoxPlotDatum) => formatValue(datum.max),
                },
            ]}
            rowKey="day"
        />
    )
}
