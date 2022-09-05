import React, { useState, useEffect } from 'react'
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
        filters: { period, date_to, breakdowns },
        aggregationTargetLabel,
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

    const maxIntervalsCount = Math.max(...results.map((result) => result.values.length))

    function dismissModal(): void {
        setModalVisible(false)
    }

    function loadMore(): void {
        loadMorePeople()
    }

    const headings = ['Cohort', 'Size', ...results.map((x) => x.label)]

    const rows = Array.from(Array(maxIntervalsCount).keys()).map((rowIndex: number) => [
        // First column is the cohort label
        <span className="RetentionTable__TextTab" key={'cohort'}>
            {breakdowns?.length
                ? results[rowIndex].label
                : period === 'Hour'
                ? dayjs(results[rowIndex].date).format('MMM D, h A')
                : dayjs.utc(results[rowIndex].date).format('MMM D')}
        </span>,
        // Second column is the first value (which is essentially the total)
        <span className="RetentionTable__TextTab" key={'cohort-size'}>
            {results[rowIndex].values[0].count}
        </span>,
        // All other columns are rendered as expected
        ...results[rowIndex].values.map((row, columIndex) => (
            <>
                {columIndex >= results[rowIndex].values.length
                    ? ''
                    : renderPercentage(
                          row['count'],
                          results[rowIndex].values[0]['count'],
                          isLatestPeriod && columIndex === results[rowIndex].values.length - 1,
                          columIndex === 0
                      )}
            </>
        )),
    ])

    return (
        <>
            <table className="RetentionTable" data-attr="retention-table">
                <tbody>
                    <tr>
                        {headings.map((heading) => (
                            <th key={heading}>{heading}</th>
                        ))}
                    </tr>

                    {rows.map((row, index) => (
                        <tr
                            key={index}
                            onClick={() => {
                                if (!inCardView && index !== undefined) {
                                    loadPeople(index)
                                    setModalVisible(true)
                                    selectRow(index)
                                }
                            }}
                        >
                            {row.map((x, j) => (
                                <td key={j}>{x}</td>
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
                    dismissModal={dismissModal}
                    actorsLoading={peopleLoading}
                    loadMore={loadMore}
                    loadingMore={loadingMore}
                    aggregationTargetLabel={aggregationTargetLabel}
                />
            )}
        </>
    )
}

const renderPercentage = (value: number, total: number, latest = false, periodZero = false): JSX.Element => {
    const _percentage = total > 0 ? (100.0 * value) / total : 0
    const percentageBasisForColor = periodZero ? 100 : _percentage // So that Period 0 is always shown consistently
    const color = percentageBasisForColor >= 65 ? 'var(--white)' : 'var(--default)'

    const backgroundColor = `rgb(4, 118, 251, ${(percentageBasisForColor / 100).toFixed(2)})` // rgb of var(--data-blue)

    const numberCell = (
        <div
            className={clsx('RetentionTable__Tab', { 'RetentionTable__Tab--period': latest })}
            style={!latest ? { backgroundColor, color } : undefined}
        >
            {_percentage.toFixed(1)}%{latest && '*'}
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
