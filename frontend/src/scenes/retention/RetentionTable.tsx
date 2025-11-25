import './RetentionTable.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import React from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { gradateColor } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { OVERALL_MEAN_KEY, retentionLogic } from './retentionLogic'
import { retentionModalLogic } from './retentionModalLogic'
import { retentionTableLogic } from './retentionTableLogic'
import { NO_BREAKDOWN_VALUE } from './types'

export function RetentionTable({
    inSharedMode = false,
    embedded = false,
}: {
    inSharedMode?: boolean
    embedded?: boolean
}): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const {
        tableRowsSplitByBreakdownValue,
        hideSizeColumn,
        retentionVizOptions,
        theme,
        expandedBreakdowns,
        retentionMeans,
        breakdownDisplayNames,
        tableHeaders,
        retentionFilter,
    } = useValues(retentionTableLogic(insightProps))
    const { toggleBreakdown, setHoveredColumn } = useActions(retentionTableLogic(insightProps))
    const { hoveredColumn } = useValues(retentionTableLogic(insightProps))
    const { updateInsightFilter } = useActions(retentionLogic(insightProps))
    const { openModal } = useActions(retentionModalLogic(insightProps))

    const selectedInterval = retentionFilter?.selectedInterval ?? null
    const allowSelectingColumns = !insightProps.dashboardId && !inSharedMode && !embedded

    const backgroundColor = theme?.['preset-1'] || '#000000' // Default to black if no color found
    const backgroundColorMean = theme?.['preset-2'] || '#000000' // Default to black if no color found
    const { isDarkModeOn } = useValues(themeLogic)

    // only one breakdown value so don't need to highlight using different colors/autoexpand it
    const isSingleBreakdown = Object.keys(tableRowsSplitByBreakdownValue).length === 1

    return (
        <table
            className={clsx('RetentionTable', {
                'RetentionTable--small-layout': retentionVizOptions?.useSmallLayout,
                'RetentionTable--allow-selecting-columns': allowSelectingColumns,
            })}
            data-attr="retention-table"
            // eslint-disable-next-line react/forbid-dom-props
            style={
                {
                    '--retention-table-color': backgroundColor,
                } as React.CSSProperties
            }
        >
            <tbody>
                <tr>
                    <th className="bg whitespace-nowrap">Cohort</th>
                    {!hideSizeColumn && <th className="bg">Size</th>}
                    {tableHeaders.map((header, columnIndex) => (
                        <th
                            key={header}
                            className={clsx({
                                'RetentionTable__SelectedColumn--header': columnIndex === selectedInterval,
                                'RetentionTable__HoveredColumn--header': columnIndex === hoveredColumn,
                            })}
                            onClick={() => {
                                if (allowSelectingColumns) {
                                    updateInsightFilter({
                                        selectedInterval: columnIndex === selectedInterval ? null : columnIndex,
                                    })
                                }
                            }}
                            onMouseEnter={() => {
                                if (allowSelectingColumns) {
                                    setHoveredColumn(columnIndex)
                                }
                            }}
                            onMouseLeave={() => {
                                if (allowSelectingColumns) {
                                    setHoveredColumn(null)
                                }
                            }}
                            style={{
                                cursor: allowSelectingColumns ? 'pointer' : 'default',
                            }}
                        >
                            {header}
                        </th>
                    ))}
                </tr>

                {Object.entries(tableRowsSplitByBreakdownValue).map(([breakdownValue, cohortRows], breakdownIndex) => {
                    const noBreakdown = breakdownValue === NO_BREAKDOWN_VALUE
                    const keyForMeanData = noBreakdown ? OVERALL_MEAN_KEY : breakdownValue
                    const meanData = retentionMeans[keyForMeanData]

                    return (
                        <React.Fragment key={breakdownIndex}>
                            {/* Mean row */}
                            <tr
                                onClick={() => toggleBreakdown(breakdownValue)}
                                className={clsx('cursor-pointer', {
                                    'bg-slate-100':
                                        !isSingleBreakdown && !isDarkModeOn && expandedBreakdowns[breakdownValue],
                                })}
                            >
                                <td className="pr-2 whitespace-nowrap">
                                    <div className="flex items-center gap-2">
                                        {expandedBreakdowns[breakdownValue] ? (
                                            <IconChevronDown />
                                        ) : (
                                            <IconChevronRight />
                                        )}
                                        <span>
                                            {breakdownValue === NO_BREAKDOWN_VALUE
                                                ? 'Mean'
                                                : breakdownDisplayNames[breakdownValue] || breakdownValue}{' '}
                                        </span>
                                    </div>
                                </td>

                                {!hideSizeColumn && (
                                    <td>
                                        <span className="RetentionTable__TextTab">
                                            {noBreakdown
                                                ? cohortRows.length
                                                    ? Math.round((meanData?.totalCohortSize ?? 0) / cohortRows.length)
                                                    : 0
                                                : (meanData?.totalCohortSize ?? 0)}
                                        </span>
                                    </td>
                                )}

                                {tableHeaders.map((_, interval) => (
                                    <td
                                        key={interval}
                                        className={clsx({
                                            'RetentionTable__SelectedColumn--cell': interval === selectedInterval,
                                            'RetentionTable__HoveredColumn--cell':
                                                interval === hoveredColumn && interval !== selectedInterval,
                                        })}
                                    >
                                        <CohortDay
                                            percentage={meanData?.meanPercentages?.[interval] ?? 0}
                                            clickable={false}
                                            backgroundColor={backgroundColorMean}
                                        />
                                    </td>
                                ))}
                            </tr>

                            {/* Detail rows (actual cohorts) */}
                            {expandedBreakdowns[breakdownValue] &&
                                cohortRows.map((row, rowIndex) => (
                                    <tr
                                        key={rowIndex}
                                        onClick={() => {
                                            if (!inSharedMode) {
                                                openModal(
                                                    rowIndex,
                                                    breakdownValue === NO_BREAKDOWN_VALUE ? null : breakdownValue
                                                )
                                            }
                                        }}
                                        className={clsx({
                                            'bg-slate-100': !isSingleBreakdown && !isDarkModeOn,
                                        })}
                                    >
                                        <td className={clsx('pl-2 whitespace-nowrap', { 'pl-6': !isSingleBreakdown })}>
                                            {row.label}
                                        </td>
                                        {!hideSizeColumn && (
                                            <td>
                                                <span className="RetentionTable__TextTab">{row.cohortSize}</span>
                                            </td>
                                        )}
                                        {tableHeaders.map((_, columnIndex) => {
                                            const column = row.values[columnIndex]
                                            return (
                                                <td
                                                    key={columnIndex}
                                                    className={clsx({
                                                        'RetentionTable__SelectedColumn--cell':
                                                            columnIndex === selectedInterval,
                                                        'RetentionTable__HoveredColumn--cell':
                                                            columnIndex === hoveredColumn,
                                                    })}
                                                >
                                                    {column && (
                                                        <CohortDay
                                                            percentage={column.percentage}
                                                            clickable={true}
                                                            isCurrentPeriod={column.isCurrentPeriod}
                                                            backgroundColor={backgroundColor}
                                                        />
                                                    )}
                                                </td>
                                            )
                                        })}
                                    </tr>
                                ))}
                        </React.Fragment>
                    )
                })}
            </tbody>
        </table>
    )
}

function CohortDay({
    percentage,
    clickable,
    backgroundColor,
    isCurrentPeriod,
}: {
    percentage: number
    clickable: boolean
    backgroundColor: string
    isCurrentPeriod?: boolean
}): JSX.Element {
    const backgroundColorSaturation = percentage / 100
    const saturatedBackgroundColor = gradateColor(backgroundColor, backgroundColorSaturation, 0.1)
    const textColor = backgroundColorSaturation > 0.4 ? '#fff' : 'var(--text-3000)' // Ensure text contrast

    const numberCell = (
        <div
            className={clsx('RetentionTable__Tab', {
                'RetentionTable__Tab--clickable': clickable,
                'RetentionTable__Tab--period': isCurrentPeriod,
            })}
            // eslint-disable-next-line react/forbid-dom-props
            style={!isCurrentPeriod ? { backgroundColor: saturatedBackgroundColor, color: textColor } : undefined}
        >
            {percentage.toFixed(1)}%
        </div>
    )
    return isCurrentPeriod ? <Tooltip title="Period in progress">{numberCell}</Tooltip> : numberCell
}
