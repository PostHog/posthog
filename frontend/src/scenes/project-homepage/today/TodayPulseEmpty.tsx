import { Text } from '@posthog/quill'

const SHADOWS = [
    { name: 'w-3/5', value: 'w-12', series: [6, 6, 7, 7, 7, 8, 8, 8, 9, 9, 9, 10, 10, 11] },
    { name: 'w-2/5', value: 'w-10', series: [9, 10, 9, 7, 8, 9, 8, 7, 8, 9, 8, 6, 9, 9, 8, 7] },
    { name: 'w-1/2', value: 'w-9', series: [8, 9, 8, 6, 7, 8, 7, 8, 7, 8, 6, 7, 8, 7, 7, 8] },
    { name: 'w-2/5', value: 'w-14', series: [9, 9, 9, 8, 9, 9, 9, 8, 9, 9, 9, 10, 10, 10, 9, 9] },
]

function points(series: number[]): string[] {
    const max = Math.max(...series)
    const min = Math.min(...series)
    return series.map((value, index) => {
        const x = (index / (series.length - 1)) * 120
        const y = 17 - ((value - min) / (max - min || 1)) * 12
        return `${x.toFixed(1)},${y.toFixed(1)}`
    })
}

function ShadowLine({ series }: { series: number[] }): JSX.Element {
    const line = points(series)
    const [x, y] = line[line.length - 1].split(',')
    return (
        <svg viewBox="0 0 120 20" preserveAspectRatio="none" className="TodayPulse__shadowChart">
            <polyline points={line.join(' ')} />
            <circle cx={x} cy={y} r="2.5" />
        </svg>
    )
}

export function TodayPulseEmpty(): JSX.Element {
    return (
        <div className="TodayPulseEmpty" data-attr="today-pulse-empty">
            <ul className="TodayPulse TodayPulse--shadow" aria-hidden>
                {SHADOWS.map((shadow, index) => (
                    <li key={index} className="TodayPulse__metric">
                        <span className={`TodayPulse__shadowName ${shadow.name}`} />
                        <span className="TodayPulse__shadowRow">
                            <span className={`TodayPulse__shadowValue ${shadow.value}`} />
                            <span className="TodayPulse__shadowChange" />
                        </span>
                        <span className="TodayPulse__spark">
                            <ShadowLine series={shadow.series} />
                        </span>
                    </li>
                ))}
            </ul>
            <Text size="xs" variant="muted" render={<p />} className="m-0">
                Your key numbers show here once PostHog has a few days of data.
            </Text>
        </div>
    )
}
