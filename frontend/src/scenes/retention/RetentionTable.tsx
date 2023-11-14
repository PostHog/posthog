import { useActions, useValues } from 'kea'
import clsx from 'clsx'

import { insightLogic } from 'scenes/insights/insightLogic'
import { retentionTableLogic } from './retentionTableLogic'
import { retentionModalLogic } from './retentionModalLogic'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import './RetentionTable.scss'
import { BRAND_BLUE_HSL, gradateColor } from 'lib/colors'

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
                                    <span className="RetentionTable__TextTab" key={'columnIndex'}>
                                        {column}
                                    </span>
                                ) : (
                                    <CohortDay
                                        percentage={column.percentage}
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

function CohortDay({ percentage, latest }: { percentage: number; latest: boolean }): JSX.Element {
    const backgroundColorSaturation = percentage / 100
    const backgroundColor = gradateColor(BRAND_BLUE_HSL, backgroundColorSaturation, 0.1)
    const textColor = backgroundColorSaturation > 0.4 ? '#fff' : 'var(--default)' // Ensure text contrast

    const numberCell = (
        <div
            className={clsx('RetentionTable__Tab', { 'RetentionTable__Tab--period': latest })}
            // eslint-disable-next-line react/forbid-dom-props
            style={!latest ? { backgroundColor, color: textColor } : undefined}
        >
            {percentage.toFixed(1)}%
        </div>
    )
    return latest ? <Tooltip title="Period in progress">{numberCell}</Tooltip> : numberCell
}
