import { useMemo } from 'react'

import { LemonCheckbox, LemonTable, LemonTableColumn, LemonTableColumns } from '@posthog/lemon-ui'

import { getSeriesColor } from 'lib/colors'
import { dayjs } from 'lib/dayjs'

import { BillingSeriesType } from './BillingChart'
import { BILLING_TABLE_PAGE_SIZE } from './constants'

export function SeriesColorDot({ colorIndex }: { colorIndex: number }): JSX.Element {
    return <div className={`series-color-dot series-color-dot-${colorIndex % 15}`} />
}

export interface BillingDataTableProps {
    series: BillingSeriesType[]
    dates: string[]
    isLoading?: boolean
    hiddenSeries: number[]
    toggleSeries: (id: number) => void
    toggleAllSeries: () => void
    valueFormatter?: (value: number) => string | number
    totalLabel?: string
}

const defaultFormatter = (value: number): string => value.toLocaleString()

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
    // A set, not the array: `includes` inside a row render is a linear scan, so an organization
    // with ten thousand series would do ten thousand scans per render.
    const hidden = useMemo(() => new Set(hiddenSeries), [hiddenSeries])

    // Summed once per series rather than inside the sorter's comparator, which would call
    // reduce() on both operands for every comparison.
    const totals = useMemo(
        () => new Map(series.map((s) => [s.id, s.data.reduce((sum, value) => sum + value, 0)])),
        [series]
    )

    const headerChecked: boolean | 'indeterminate' =
        hiddenSeries.length === 0 ? true : hiddenSeries.length === series.length ? false : 'indeterminate'

    const dateColumns = useMemo<LemonTableColumn<BillingSeriesType, keyof BillingSeriesType | undefined>[]>(() => {
        if (!dates || dates.length === 0) {
            return []
        }
        return dates.map((date, colIndex) => {
            const dateIndex = colIndex
            return {
                width: `${100 / (dates.length + 1)}%`,
                title: dayjs(date).format('MMM D'),
                render: (_: unknown, record: BillingSeriesType) => {
                    const value = record.data[dateIndex]
                    return (
                        <div className="text-right">
                            {dateIndex >= 0 && dateIndex < record.data.length
                                ? valueFormatter(value)
                                : valueFormatter(0)}{' '}
                        </div>
                    )
                },
                key: `date-${colIndex}`,
                sorter: (a: BillingSeriesType, b: BillingSeriesType) =>
                    (a.data[dateIndex] ?? 0) - (b.data[dateIndex] ?? 0),
                align: 'right',
            }
        })
    }, [dates, valueFormatter])

    const totalColumn = useMemo<LemonTableColumn<BillingSeriesType, keyof BillingSeriesType | undefined>>(
        () => ({
            width: `${100 / (dates.length + 1)}%`,
            title: totalLabel,
            render: (_: unknown, record: BillingSeriesType) => (
                <div className="text-right font-semibold">{valueFormatter(totals.get(record.id) ?? 0)}</div>
            ),
            key: 'total',
            sorter: (a: BillingSeriesType, b: BillingSeriesType) => (totals.get(a.id) ?? 0) - (totals.get(b.id) ?? 0),
            align: 'right',
        }),
        [dates.length, totalLabel, valueFormatter, totals]
    )

    // Combine series checkbox column, total column, and all date columns
    const columns: LemonTableColumns<BillingSeriesType> = useMemo(
        () => [
            {
                title: (
                    <div className="flex items-center">
                        <LemonCheckbox checked={headerChecked} onChange={toggleAllSeries} className="mr-2" />
                        <span>Series</span>
                    </div>
                ),
                render: (_, record: BillingSeriesType) => {
                    const isHidden = hidden.has(record.id)
                    return (
                        <div className="flex items-center gap-1">
                            <LemonCheckbox
                                checked={!isHidden}
                                onChange={() => toggleSeries(record.id)}
                                className="mr-2"
                            />
                            <SeriesColorDot colorIndex={record.id} />
                            <span className="font-medium whitespace-nowrap overflow-hidden text-ellipsis max-w-xs">
                                {record.label}
                            </span>
                        </div>
                    )
                },
                key: 'series',
                sorter: (a: BillingSeriesType, b: BillingSeriesType) => a.label.localeCompare(b.label),
            },
            totalColumn,
            ...dateColumns,
        ],
        [headerChecked, totalColumn, dateColumns, toggleSeries, toggleAllSeries, hidden]
    )

    return (
        <div className="overflow-x-auto border rounded bg-bg-light">
            <LemonTable
                data-attr="billing-data-table"
                dataSource={series}
                columns={columns}
                loading={isLoading}
                embedded
                size="small"
                rowClassName={(record) => (hidden.has(record.id) ? 'opacity-50' : '')}
                defaultSorting={{
                    columnKey: 'total',
                    order: -1,
                }}
                rowRibbonColor={(record) => getSeriesColor(record.id % 15)}
                pagination={{ pageSize: BILLING_TABLE_PAGE_SIZE }}
                firstColumnSticky
            />
        </div>
    )
}
