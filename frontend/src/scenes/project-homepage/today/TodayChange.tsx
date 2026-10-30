import { type TodayTone, useTodayTonePalette } from './todayTone'

export function TodayChange({ change, tone }: { change: number | null; tone: TodayTone }): JSX.Element | null {
    const palette = useTodayTonePalette()
    if (change === null) {
        return null
    }
    const rounded = Math.round(change)
    return (
        <span
            className="TodayChange"
            translate="no"
            // eslint-disable-next-line react/forbid-dom-props
            style={tone === 'neutral' ? undefined : { color: palette[tone] }}
        >
            {rounded === 0 ? '0%' : `${rounded > 0 ? '+' : '−'}${Math.abs(rounded)}%`}
        </span>
    )
}
