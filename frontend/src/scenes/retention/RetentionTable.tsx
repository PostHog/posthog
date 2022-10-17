import { useState, useEffect } from 'react'
import { useValues, useActions } from 'kea'
import { retentionTableLogic } from './retentionTableLogic'
import { Tooltip } from 'lib/components/Tooltip'
import { RetentionTablePayload, RetentionTablePeoplePayload } from 'scenes/retention/types'
import clsx from 'clsx'
import { insightLogic } from 'scenes/insights/insightLogic'
import { dayjs } from 'lib/dayjs'
import './RetentionTable.scss'

import { RetentionModal } from './RetentionModal'

export function RetentionTable({ inCardView = false }: { inCardView?: boolean }): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const logic = retentionTableLogic(insightProps)
    const {
        results: _results,
        resultsLoading,
        peopleLoading,
        people: _people,
        loadingMore,
        filters: { period, date_to },
        aggregationTargetLabel,
        tableHeaders,
        tableRows,
    } = useValues(logic)
    const results = _results as RetentionTablePayload[]
    const people = _people as RetentionTablePeoplePayload

    const { loadPeople, loadMorePeople } = useActions(logic)
    const [modalVisible, setModalVisible] = useState(false)
    const [selectedRow, selectRow] = useState(0)
    const [isLatestPeriod, setIsLatestPeriod] = useState(false)

    useEffect(() => {
        setIsLatestPeriod(periodIsLatest(date_to || null, period || null))
    }, [date_to, period])

    if (resultsLoading || !results?.length) {
        return null
    }

    return (
        <>
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
                                if (!inCardView && rowIndex !== undefined) {
                                    loadPeople(rowIndex)
                                    setModalVisible(true)
                                    selectRow(rowIndex)
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

            {results && (
                <RetentionModal
                    results={results}
                    actors={people}
                    selectedRow={selectedRow}
                    visible={modalVisible}
                    dismissModal={() => setModalVisible(false)}
                    actorsLoading={peopleLoading}
                    loadMore={loadMorePeople}
                    loadingMore={loadingMore}
                    aggregationTargetLabel={aggregationTargetLabel}
                />
            )}
        </>
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
