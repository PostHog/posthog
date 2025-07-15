import './RetentionTable.scss'

import { IconChevronDown } from '@posthog/icons'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { IconChevronRight } from 'lib/lemon-ui/icons'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { gradateColor, range } from 'lib/utils'
import React from 'react'
import { insightLogic } from 'scenes/insights/insightLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { DEFAULT_RETENTION_TOTAL_INTERVALS, OVERALL_MEAN_KEY, RETENTION_EMPTY_BREAKDOWN_VALUE } from './retentionLogic'
import { retentionModalLogic } from './retentionModalLogic'
import { retentionTableLogic } from './retentionTableLogic'
import { NO_BREAKDOWN_VALUE } from './types'

export function RetentionTable({ inSharedMode = false }: { inSharedMode?: boolean }): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const {
        tableRowsSplitByBreakdownValue,
        hideSizeColumn,
        retentionVizOptions,
        theme,
        retentionFilter,
        expandedBreakdowns,
        retentionMeans,
    } = useValues(retentionTableLogic(insightProps))
    const { toggleBreakdown } = useActions(retentionTableLogic(insightProps))
    const { openModal } = useActions(retentionModalLogic(insightProps))
    const backgroundColor = theme?.['preset-1'] || '#000000' // Default to black if no color found
    const backgroundColorMean = theme?.['preset-2'] || '#000000' // Default to black if no color found
    const { isDarkModeOn } = useValues(themeLogic)

    const totalIntervals = retentionFilter?.totalIntervals ?? DEFAULT_RETENTION_TOTAL_INTERVALS
    // only one breakdown value so don't need to highlight using different colors/autoexpand it
    const isSingleBreakdown = Object.keys(tableRowsSplitByBreakdownValue).length === 1

    return (
        <table
            className={clsx('RetentionTable', { 'RetentionTable--small-layout': retentionVizOptions?.useSmallLayout })}
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
                    {range(0, totalIntervals).map((interval) => (
                        <th key={interval}>{`${retentionFilter?.period} ${interval}`}</th>
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
                                            {noBreakdown
                                                ? 'Mean'
                                                : breakdownValue === null || breakdownValue === ''
                                                ? RETENTION_EMPTY_BREAKDOWN_VALUE
                                                : breakdownValue}{' '}
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
                                                : meanData?.totalCohortSize ?? 0}
                                        </span>
                                    </td>
                                )}

                                {range(0, totalIntervals).map((interval) => (
                                    <td key={interval}>
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
                                                openModal(rowIndex)
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
                                        {row.values.map((column, columnIndex) => (
                                            <td key={columnIndex}>
                                                <CohortDay
                                                    percentage={column.percentage}
                                                    clickable={true}
                                                    isCurrentPeriod={column.isCurrentPeriod}
                                                    backgroundColor={backgroundColor}
                                                />
                                            </td>
                                        ))}
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
