import { useValues } from 'kea'

import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { insightLogic } from 'scenes/insights/insightLogic'

import { BoxPlotDatum } from '~/queries/schema/schema-general'

import { boxPlotChartLogic } from './boxPlotChartLogic'

export function BoxPlotResultsTable(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { boxplotData } = useValues(boxPlotChartLogic(insightProps))

    if (!boxplotData || boxplotData.length === 0) {
        return null
    }

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
                    render: (_, datum: BoxPlotDatum) => datum.min.toLocaleString(),
                },
                {
                    title: '25th percentile',
                    key: 'p25',
                    align: 'right',
                    render: (_, datum: BoxPlotDatum) => datum.p25.toLocaleString(),
                },
                {
                    title: 'Median',
                    key: 'median',
                    align: 'right',
                    render: (_, datum: BoxPlotDatum) => datum.median.toLocaleString(),
                },
                {
                    title: 'Mean',
                    key: 'mean',
                    align: 'right',
                    render: (_, datum: BoxPlotDatum) => datum.mean.toLocaleString(),
                },
                {
                    title: '75th percentile',
                    key: 'p75',
                    align: 'right',
                    render: (_, datum: BoxPlotDatum) => datum.p75.toLocaleString(),
                },
                {
                    title: 'Max',
                    key: 'max',
                    align: 'right',
                    render: (_, datum: BoxPlotDatum) => datum.max.toLocaleString(),
                },
            ]}
            rowKey="day"
        />
    )
}
