import { useValues } from 'kea'

import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { HistogramGraphDatum } from '~/types'

export function FunnelTimeToConvertTable(): JSX.Element | null {
    const { insightProps, insightLoading } = useValues(insightLogic)
    const { histogramGraphData, conversionMetrics } = useValues(funnelDataLogic(insightProps))

    if (!histogramGraphData || histogramGraphData.length === 0) {
        return null
    }

    const columns: LemonTableColumns<HistogramGraphDatum> = [
        {
            title: 'Time to convert',
            key: 'time_range',
            render: (_, datum) =>
                `${humanFriendlyDuration(datum.bin0, { maxUnits: 2 })} – ${humanFriendlyDuration(datum.bin1, {
                    maxUnits: 2,
                })}`,
        },
        {
            title: 'Conversions',
            key: 'count',
            align: 'right',
            render: (_, datum) => humanFriendlyNumber(datum.count),
        },
        {
            title: '% of total',
            key: 'percent',
            align: 'right',
            render: (_, datum) => datum.label || '0%',
        },
    ]

    return (
        <LemonTable
            dataSource={histogramGraphData}
            columns={columns}
            loading={insightLoading}
            rowKey="id"
            data-attr="funnel-time-to-convert-table"
            footer={
                conversionMetrics.averageTime ? (
                    <div className="flex items-center justify-between px-2 py-1">
                        <span className="font-medium">Average time to convert</span>
                        <span>{humanFriendlyDuration(conversionMetrics.averageTime, { maxUnits: 3 })}</span>
                    </div>
                ) : undefined
            }
        />
    )
}
