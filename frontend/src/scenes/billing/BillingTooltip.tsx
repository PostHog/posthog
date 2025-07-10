import { SeriesColorDot } from './BillingLineGraph'

export interface BillingLineGraphTooltipSeriesItem {
    id: number | string
    label: string
    value: number
    formattedValue: string
    color: string
    datasetIndex: number
}

export interface BillingLineGraphTooltipProps {
    title: string
    sortedSeries: BillingLineGraphTooltipSeriesItem[]
}

export function BillingLineGraphTooltip({ title, sortedSeries }: BillingLineGraphTooltipProps): JSX.Element {
    return (
        <div className="space-y-1">
            <div className="text-text-primary font-semibold">{title}</div>
            {sortedSeries.map((item) => (
                <div key={item.id} className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1">
                        <SeriesColorDot colorIndex={item.datasetIndex} />
                        <span className="text-text-secondary max-w-xs overflow-hidden text-ellipsis whitespace-nowrap">
                            {item.label}
                        </span>
                    </div>
                    <span className="text-text-primary whitespace-nowrap font-medium">{item.formattedValue}</span>
                </div>
            ))}
        </div>
    )
}
