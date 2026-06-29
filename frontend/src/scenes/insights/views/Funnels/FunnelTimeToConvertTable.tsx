import { useValues } from 'kea'

import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { buildTimeToConvertCompareRows, TimeToConvertCompareRow } from './funnelTimeToConvertTableUtils'

type TimeToConvertColumn = LemonTableColumn<TimeToConvertCompareRow, keyof TimeToConvertCompareRow | undefined>

const timeRangeColumn: TimeToConvertColumn = {
    title: 'Time to convert',
    key: 'time_range',
    render: (_, row) =>
        `${humanFriendlyDuration(row.bin0, { maxUnits: 2 })} – ${humanFriendlyDuration(row.bin1, { maxUnits: 2 })}`,
}

const conversionsColumn: TimeToConvertColumn = {
    title: 'Conversions',
    key: 'count',
    align: 'right',
    render: (_, row) => humanFriendlyNumber(row.count),
}

const percentColumn: TimeToConvertColumn = {
    title: '% of total',
    key: 'percent',
    align: 'right',
    render: (_, row) => row.label || '0%',
}

const previousConversionsColumn: TimeToConvertColumn = {
    title: 'Conversions',
    key: 'previous_count',
    align: 'right',
    render: (_, row) => (row.previous ? humanFriendlyNumber(row.previous.count) : '–'),
}

const previousPercentColumn: TimeToConvertColumn = {
    title: '% of total',
    key: 'previous_percent',
    align: 'right',
    render: (_, row) => row.previous?.label || '–',
}

export function FunnelTimeToConvertTable(): JSX.Element | null {
    const { insightProps, insightLoading } = useValues(insightLogic)
    const { histogramGraphData, histogramGraphDataPrevious, timeConversionResultsPrevious, conversionMetrics } =
        useValues(funnelDataLogic(insightProps))

    if (!histogramGraphData || histogramGraphData.length === 0) {
        return null
    }

    const isComparing = !!histogramGraphDataPrevious && histogramGraphDataPrevious.length > 0
    const rows = buildTimeToConvertCompareRows(histogramGraphData, histogramGraphDataPrevious)

    const columns: LemonTableColumns<TimeToConvertCompareRow> = isComparing
        ? [
              { children: [timeRangeColumn] },
              { title: 'Current', children: [conversionsColumn, percentColumn] },
              { title: 'Previous', children: [previousConversionsColumn, previousPercentColumn] },
          ]
        : [timeRangeColumn, conversionsColumn, percentColumn]

    const previousMedianTime = timeConversionResultsPrevious?.median_conversion_time

    return (
        <LemonTable
            dataSource={rows}
            columns={columns}
            loading={insightLoading}
            rowKey="id"
            data-attr="funnel-time-to-convert-table"
            footer={
                conversionMetrics.medianTime ? (
                    <div className="flex items-center justify-between px-2 py-1">
                        <span className="font-medium">Median time to convert</span>
                        <span>
                            {humanFriendlyDuration(conversionMetrics.medianTime, { maxUnits: 3 })}
                            {isComparing && (
                                <span className="text-secondary">
                                    {' '}
                                    (current) ·{' '}
                                    {previousMedianTime
                                        ? `${humanFriendlyDuration(previousMedianTime, { maxUnits: 3 })} (previous)`
                                        : '– (previous)'}
                                </span>
                            )}
                        </span>
                    </div>
                ) : undefined
            }
        />
    )
}
