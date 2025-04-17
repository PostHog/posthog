import clsx from 'clsx'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { gradateColor, humanFriendlyLargeNumber } from 'lib/utils'

interface HeatMapCellProps {
    value: number
    maxValue: number
    backgroundColor: string
    fontSize: number
    showTooltip: boolean
    dayAndTime: string
}

export function HeatMapCell({
    value,
    maxValue,
    backgroundColor,
    fontSize,
    showTooltip,
    dayAndTime,
}: HeatMapCellProps): JSX.Element {
    const backgroundColorSaturation = maxValue === 0 ? 0 : Math.min(1, value / maxValue)
    const saturatedBackgroundColor = gradateColor(backgroundColor, backgroundColorSaturation, 0.1)
    const textColor = backgroundColorSaturation > 0.4 ? '#fff' : 'var(--text-3000)'

    const cell = (
        <div
            className={clsx('EventsHeatMap__Cell')}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ fontSize, backgroundColor: saturatedBackgroundColor, color: textColor }}
        >
            {humanFriendlyLargeNumber(value)}
        </div>
    )

    return showTooltip ? (
        <Tooltip delayMs={0} title={`${dayAndTime} - ${humanFriendlyLargeNumber(value)}`}>
            {cell}
        </Tooltip>
    ) : (
        cell
    )
}
