import { useValues, useActions } from 'kea'
import clsx from 'clsx'
import { dayjs } from 'lib/dayjs'

import { insightLogic } from 'scenes/insights/insightLogic'
import { retentionLogic } from './retentionLogic'
import { retentionTableLogic } from './retentionTableLogic'
import { retentionModalLogic } from './retentionModalLogic'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import './RetentionTable.scss'

export function RetentionTable({ inCardView = false }: { inCardView?: boolean }): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const {
        results,
        resultsLoading,
        filters: { period, date_to },
    } = useValues(retentionLogic(insightProps))
    const { tableHeaders, tableRows } = useValues(retentionTableLogic(insightProps))
    const { openModal } = useActions(retentionModalLogic(insightProps))

    const isLatestPeriod = periodIsLatest(date_to || null, period || null)

    if (resultsLoading || !results?.length) {
        return null
    }

    return (
        <table className="RetentionTable" data-attr="retention-table">
            <tbody>
                <tr>
                    {tableHeaders.map((heading) => (
                        <th key={heading}>{heading}</th>
                    ))}
                </tr>

                {tableRows.map((row, rowIndex) => (
                    <tr
                        key={rowIndex}
                        onClick={() => {
                            if (!inCardView) {
                                openModal(rowIndex)
                            }
                        }}
                    >
                        {row.map((column, columnIndex) => (
                            <td key={columnIndex}>
                                {columnIndex <= 1 ? (
                                    <span className="RetentionTable__TextTab" key={'columnIndex'}>
                                        {column}
                                    </span>
                                ) : (
                                    renderPercentage(
                                        column.percentage,
                                        isLatestPeriod && columnIndex === row.length - 1,
                                        columnIndex === 2 // First result column renders differently
                                    )
                                )}
                            </td>
                        ))}
                    </tr>
                ))}
            </tbody>
        </table>
    )
}

const renderPercentage = (percentage: number, latest = false, firstColumn = false): JSX.Element => {
    const color = firstColumn ? 'var(--white)' : 'var(--default)'
    const backgroundColor = firstColumn
        ? `var(--retention-table-dark-color)`
        : `rgb(81, 171, 231, ${(percentage / 100).toFixed(2)})` // rgb of var(--retention-table-color)

    const numberCell = (
        <div
            className={clsx('RetentionTable__Tab', { 'RetentionTable__Tab--period': latest })}
            // eslint-disable-next-line react/forbid-dom-props
            style={!latest ? { backgroundColor, color } : undefined}
        >
            {percentage.toFixed(1)}%
        </div>
    )
    return latest ? <Tooltip title="Period in progress">{numberCell}</Tooltip> : numberCell
}

const periodIsLatest = (date_to: string | null, period: string | null): boolean => {
    if (!date_to || !period) {
        return true
    }

    const curr = dayjs(date_to)
    if (
        (period == 'Hour' && curr.isSame(dayjs(), 'hour')) ||
        (period == 'Day' && curr.isSame(dayjs(), 'day')) ||
        (period == 'Week' && curr.isSame(dayjs(), 'week')) ||
        (period == 'Month' && curr.isSame(dayjs(), 'month'))
    ) {
        return true
    } else {
        return false
    }
}
