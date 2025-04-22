import { LemonCheckbox, LemonTable, LemonTableColumn, LemonTableColumns } from '@posthog/lemon-ui'
import { dayjs } from 'lib/dayjs'

import { BillingSeriesType, SeriesColorDot } from './BillingLineGraph' // Reuse type and color dot

// Props for the reusable table component
export interface BillingDataTableProps {
    series: BillingSeriesType[]
    dates: string[]
    isLoading?: boolean
    hiddenSeries: number[]
    toggleSeries: (id: number) => void
    toggleAllSeries: () => void
    /** Function to format the display of values in the table cells */
    valueFormatter?: (value: number) => string | number
    /** Label for the total column */
    totalLabel?: string
}

// Default formatter using locale string
const defaultFormatter = (value: number): string => value.toLocaleString()

// Reusable BillingDataTable component
export function BillingDataTable({
    series,
    dates,
    isLoading,
    hiddenSeries,
    toggleSeries,
    toggleAllSeries,
    valueFormatter = defaultFormatter,
    totalLabel = 'Total',
}: BillingDataTableProps): JSX.Element {
    // Get date columns for the table - show all dates
    const getDateColumns = (): LemonTableColumn<BillingSeriesType, keyof BillingSeriesType | undefined>[] => {
        if (!dates || dates.length === 0) {
            return []
        }

        return dates.map((date, colIndex) => {
            const dateIndex = colIndex
            return {
                title: dayjs(date).format('MMM D'),
                render: (_, record: BillingSeriesType) => {
                    const value = record.data[dateIndex]
                    return (
                        <div className="text-right">
                            {dateIndex >= 0 && dateIndex < record.data.length
                                ? valueFormatter(value) // Use formatter
                                : valueFormatter(0)}{' '}
                            {/* Format zero value */}
                        </div>
                    )
                },
                key: `date-${colIndex}`,
                sorter: (a: BillingSeriesType, b: BillingSeriesType) => {
                    return (a.data[dateIndex] || 0) - (b.data[dateIndex] || 0)
                },
                align: 'right',
            }
        })
    }

    // Define the total column
    const totalColumn: LemonTableColumn<BillingSeriesType, keyof BillingSeriesType | undefined> = {
        title: totalLabel, // Use prop
        render: (_, record: BillingSeriesType) => {
            // Prefer sum of data array for consistency, 'count' field might be ambiguous/deprecated
            const total = record.data.reduce((sum, val) => sum + val, 0)
            return <div className="text-right font-semibold">{valueFormatter(total)}</div> // Use formatter
        },
        key: 'total',
        sorter: (a: BillingSeriesType, b: BillingSeriesType) => {
            const totalA = a.data.reduce((sum, val) => sum + val, 0)
            const totalB = b.data.reduce((sum, val) => sum + val, 0)
            return totalA - totalB
        },
        align: 'right',
    }

    // Define table columns
    const columns: LemonTableColumns<BillingSeriesType> = [
        {
            title: (
                <div className="flex items-center">
                    <LemonCheckbox
                        checked={series.length > 0 && hiddenSeries.length === 0}
                        onChange={toggleAllSeries}
                        className="mr-2"
                    />
                    <span>Series</span>
                </div>
            ),
            render: (_, record: BillingSeriesType) => {
                const isHidden = hiddenSeries.includes(record.id)
                return (
                    <div className="flex items-center">
                        <LemonCheckbox checked={!isHidden} onChange={() => toggleSeries(record.id)} className="mr-2" />
                        <SeriesColorDot colorIndex={record.id} />
                        <span className="font-medium">{record.label}</span>
                    </div>
                )
            },
            key: 'series',
            sorter: (a: BillingSeriesType, b: BillingSeriesType) => a.label.localeCompare(b.label),
        },
        totalColumn,
        ...getDateColumns(),
    ]

    return (
        <div className="overflow-x-auto border rounded">
            <LemonTable
                dataSource={series}
                columns={columns}
                loading={isLoading}
                className="bg-white"
                embedded
                size="small"
                rowClassName={(record) => (hiddenSeries.includes(record.id) ? 'opacity-50' : '')}
            />
        </div>
    )
}
