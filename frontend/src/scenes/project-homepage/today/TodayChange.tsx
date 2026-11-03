import { type TodayTone, useTodayTonePalette } from './todayTone'

export function TodayChange({ change, tone }: { change: number | null; tone: TodayTone }): JSX.Element | null {
    const palette = useTodayTonePalette()
    if (change === null) {
        return null
    }
    const rounded = Math.round(change)
    const text =
        rounded >= 1000
            ? `${Math.round(1 + change / 100)}×`
            : rounded === 0
              ? '0%'
              : `${rounded > 0 ? '+' : '−'}${Math.abs(rounded)}%`
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
