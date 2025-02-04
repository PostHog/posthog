import './RetentionTable.scss'

import clsx from 'clsx'
import { mean, sum } from 'd3'
import { useActions, useValues } from 'kea'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { gradateColor, range } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'

import { retentionModalLogic } from './retentionModalLogic'
import { retentionTableLogic } from './retentionTableLogic'

export function RetentionTable({ inSharedMode = false }: { inSharedMode?: boolean }): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { tableHeaders, tableRows, isLatestPeriod, hideSizeColumn, retentionVizOptions, theme, retentionFilter } =
        useValues(retentionTableLogic(insightProps))
    const { openModal } = useActions(retentionModalLogic(insightProps))
    const backgroundColor = theme?.['preset-1'] || '#000000' // Default to black if no color found
    const backgroundColorMean = theme?.['preset-2'] || '#000000' // Default to black if no color found
    const showMean = retentionFilter?.showMean || null

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
                    {tableHeaders.map((heading) => (
                        <th key={heading}>{heading}</th>
                    ))}
                </tr>

                {showMean === 'weighted' && tableRows.length > 0 ? (
                    <tr className="border-b" key={-2}>
                        {range(0, tableRows[0].length).map((columnIndex) => (
                            <td key={columnIndex} className="pb-2">
                                {columnIndex <= (hideSizeColumn ? 0 : 1) ? (
                                    columnIndex == 0 ? (
                                        <span className="RetentionTable__TextTab">Weighted Mean</span>
                                    ) : null
                                ) : (
                                    <CohortDay
                                        percentage={
                                            (() => {
                                                const validRows = tableRows.filter((row) => {
                                                    return !(
                                                        (columnIndex >= row.length - 1 && isLatestPeriod) ||
                                                        !row[columnIndex] ||
                                                        row[columnIndex].count <= 0
                                                    )
                                                })
                                                if (validRows.length === 0) {
                                                    return 0
                                                }
                                                const weights = validRows.map((row) =>
                                                    parseInt(row[1]?.toString() || '0')
                                                )
                                                const weightedSum = sum(
                                                    validRows.map(
                                                        (row, i) => (row[columnIndex]?.percentage || 0) * weights[i]
                                                    )
                                                )
                                                const totalWeight = sum(weights)
                                                return totalWeight > 0 ? weightedSum / totalWeight : 0
                                            })() || 0
                                        }
                                        latest={isLatestPeriod && columnIndex == tableRows[0].length - 1}
                                        clickable={false}
                                        backgroundColor={backgroundColorMean}
                                    />
                                )}
                            </td>
                        ))}
                    </tr>
                ) : undefined}

                {showMean === 'simple' && tableRows.length > 0 ? (
                    <tr className="border-b" key={-1}>
                        {range(0, tableRows[0].length).map((columnIndex) => (
                            <td key={columnIndex} className="pb-2">
                                {columnIndex <= (hideSizeColumn ? 0 : 1) ? (
                                    columnIndex == 0 ? (
                                        <span className="RetentionTable__TextTab">Mean</span>
                                    ) : null
                                ) : (
                                    <CohortDay
                                        percentage={
                                            mean(
                                                tableRows.map((row) => {
                                                    // Don't include the last item in a row, which is an incomplete time period
                                                    // Also don't include the percentage if the cohort size (count) is 0 or less
                                                    if (
                                                        (columnIndex >= row.length - 1 && isLatestPeriod) ||
                                                        !row[columnIndex] ||
                                                        row[columnIndex].count <= 0
                                                    ) {
                                                        return null
                                                    }
                                                    return row[columnIndex].percentage
                                                })
                                            ) || 0
                                        }
                                        latest={isLatestPeriod && columnIndex == tableRows[0].length - 1}
                                        clickable={false}
                                        backgroundColor={backgroundColorMean}
                                    />
                                )}
                            </td>
                        ))}
                    </tr>
                ) : undefined}

                {tableRows.map((row, rowIndex) => (
                    <tr
                        key={rowIndex}
                        onClick={() => {
                            if (!inSharedMode) {
                                openModal(rowIndex)
                            }
                        }}
                    >
                        {row.map((column, columnIndex) => (
                            <td key={columnIndex} className={clsx({ 'pt-2': rowIndex === 0 && showMean })}>
                                {columnIndex <= (hideSizeColumn ? 0 : 1) ? (
                                    <span className="RetentionTable__TextTab">{column}</span>
                                ) : (
                                    <CohortDay
                                        percentage={column.percentage}
                                        clickable={true}
                                        latest={isLatestPeriod && columnIndex === row.length - 1}
                                        backgroundColor={backgroundColor}
                                    />
                                )}
                            </td>
                        ))}
                    </tr>
                ))}
            </tbody>
        </table>
    )
}

function CohortDay({
    percentage,
    latest,
    clickable,
    backgroundColor,
}: {
    percentage: number
    latest: boolean
    clickable: boolean
    backgroundColor: string
}): JSX.Element {
    const backgroundColorSaturation = percentage / 100
    const saturatedBackgroundColor = gradateColor(backgroundColor, backgroundColorSaturation, 0.1)
    const textColor = backgroundColorSaturation > 0.4 ? '#fff' : 'var(--text-3000)' // Ensure text contrast

    const numberCell = (
        <div
            className={clsx('RetentionTable__Tab', {
                'RetentionTable__Tab--clickable': clickable,
                'RetentionTable__Tab--period': latest,
            })}
            // eslint-disable-next-line react/forbid-dom-props
            style={!latest ? { backgroundColor: saturatedBackgroundColor, color: textColor } : undefined}
        >
            {percentage.toFixed(1)}%
        </div>
    )
    return latest ? <Tooltip title="Period in progress">{numberCell}</Tooltip> : numberCell
}
