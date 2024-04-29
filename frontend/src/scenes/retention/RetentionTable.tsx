import './RetentionTable.scss'

import clsx from 'clsx'
import { mean } from 'd3'
import { useActions, useValues } from 'kea'
import { BRAND_BLUE_HSL, gradateColor } from 'lib/colors'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { range } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'

import { retentionModalLogic } from './retentionModalLogic'
import { retentionTableLogic } from './retentionTableLogic'

export function RetentionTable({ inCardView = false }: { inCardView?: boolean }): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { tableHeaders, tableRows, isLatestPeriod, hideSizeColumn, retentionVizOptions } = useValues(
        retentionTableLogic(insightProps)
    )
    const { openModal } = useActions(retentionModalLogic(insightProps))

    return (
        <table
            className={clsx('RetentionTable', { 'RetentionTable--small-layout': retentionVizOptions?.useSmallLayout })}
            data-attr="retention-table"
        >
            <tbody>
                <tr>
                    {tableHeaders.map((heading) => (
                        <th key={heading}>{heading}</th>
                    ))}
                </tr>

                {tableRows.length > 0 ? (
                    <tr className="border-b" key={-1}>
                        {range(0, tableRows[0].length).map((columnIndex) => (
                            <td key={columnIndex}>
                                {columnIndex <= (hideSizeColumn ? 0 : 1) ? (
                                    columnIndex == 0 ? (
                                        <span className="RetentionTable__TextTab">Mean</span>
                                    ) : null
                                ) : (
                                    <CohortDay
                                        percentage={
                                            mean(
                                                tableRows.map((row) => {
                                                    if (columnIndex < row.length) {
                                                        return row[columnIndex].percentage
                                                    }
                                                    return null
                                                })
                                            ) || 0
                                        }
                                        latest={false}
                                        clickable={false}
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
                            if (!inCardView) {
                                openModal(rowIndex)
                            }
                        }}
                    >
                        {row.map((column, columnIndex) => (
                            <td key={columnIndex}>
                                {columnIndex <= (hideSizeColumn ? 0 : 1) ? (
                                    <span className="RetentionTable__TextTab">{column}</span>
                                ) : (
                                    <CohortDay
                                        percentage={column.percentage}
                                        clickable={true}
                                        latest={isLatestPeriod && columnIndex === row.length - 1}
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
}: {
    percentage: number
    latest: boolean
    clickable: boolean
}): JSX.Element {
    const backgroundColorSaturation = percentage / 100
    const backgroundColor = gradateColor(BRAND_BLUE_HSL, backgroundColorSaturation, 0.1)
    const textColor = backgroundColorSaturation > 0.4 ? '#fff' : 'var(--default)' // Ensure text contrast

    const numberCell = (
        <div
            className={clsx('RetentionTable__Tab', {
                'RetentionTable__Tab--clickable': clickable,
                'RetentionTable__Tab--period': latest,
            })}
            // eslint-disable-next-line react/forbid-dom-props
            style={!latest ? { backgroundColor, color: textColor } : undefined}
        >
            {percentage.toFixed(1)}%
        </div>
    )
    return latest ? <Tooltip title="Period in progress">{numberCell}</Tooltip> : numberCell
}
