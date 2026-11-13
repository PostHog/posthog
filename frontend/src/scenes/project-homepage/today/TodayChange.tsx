import { todayChangeText } from './todayNumbers'
import { type TodayTone, useTodayTonePalette } from './todayTone'

export function TodayChange({
    change,
    tone,
    unit = '%',
    decimals = 0,
}: {
    change: number | null
    tone: TodayTone
    unit?: '%' | 'pp'
    decimals?: number
}): JSX.Element | null {
    const palette = useTodayTonePalette()
    if (change === null) {
        return null
    }
    const text = todayChangeText(change, unit, decimals)
    return (
        <span
            className="TodayChange"
            translate="no"
            // eslint-disable-next-line react/forbid-dom-props
            style={tone === 'neutral' ? undefined : { color: palette[tone] }}
        >
            {text}
        </span>
    )
}
