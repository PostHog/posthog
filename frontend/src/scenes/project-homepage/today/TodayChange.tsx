import { type TodayTone, useTodayTonePalette } from './todayTone'

export function TodayChange({
    change,
    tone,
    unit = '%',
}: {
    change: number | null
    tone: TodayTone
    unit?: '%' | 'pp'
}): JSX.Element | null {
    const palette = useTodayTonePalette()
    if (change === null) {
        return null
    }
    const rounded = unit === 'pp' ? Math.round(change * 10) / 10 : Math.round(change)
    const text =
        unit === 'pp'
            ? `${rounded > 0 ? '+' : rounded < 0 ? '−' : ''}${Math.abs(rounded)} pp`
            : rounded === 0
              ? '0%'
              : `${rounded > 0 ? '+' : '−'}${Math.abs(rounded).toLocaleString('en-US')}%`
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
