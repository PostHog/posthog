import type { CSSProperties } from 'react'

import { type EffectAxis, PLOT_WIDTHS, effectX, labelWidth, signedPercent } from '../lib/results'

function crowdsZero(value: number, axis: EffectAxis, plot: number): boolean {
    const zero = effectX(0, axis, plot)
    const zeroHalf = labelWidth('0') / 2
    const width = labelWidth(signedPercent(value))
    const gap = value < 0 ? zero - zeroHalf - width : plot - width - (zero + zeroHalf)
    return gap < 10
}

export function BetEffectAxis({ axis, metric }: { axis: EffectAxis; metric: string }): JSX.Element {
    const ends = [axis.min, axis.max].map((value) => ({
        value,
        wide: crowdsZero(value, axis, PLOT_WIDTHS.wide),
        narrow: crowdsZero(value, axis, PLOT_WIDTHS.narrow),
    }))
    return (
        <li className="BetsResults__axisRow" aria-hidden>
            <span className="BetsResults__caption">Change in {metric.toLowerCase()}, 95% interval</span>
            <div
                className="BetsResults__axis tabular-nums"
                style={{ '--interval-zero': String(effectX(0, axis, 1)) } as CSSProperties}
            >
                {axis.ticks.map((tick) => (
                    <span key={tick} className="BetsResults__tick" style={{ left: `${effectX(tick, axis, 100)}%` }} />
                ))}
                <span className="BetsResults__zero" />
                {ends.map((end) => (
                    <span
                        key={end.value}
                        className="BetsResults__tickLabel"
                        data-end={end.value < 0 ? 'min' : 'max'}
                        data-hide-wide={end.wide || undefined}
                        data-hide-narrow={end.narrow || undefined}
                    >
                        {signedPercent(end.value)}
                    </span>
                ))}
                <span className="BetsResults__tickLabel" data-end="zero">
                    0
                </span>
            </div>
        </li>
    )
}
