import type { CSSProperties } from 'react'

import type { IdeaOutcomeEnumApi } from '../generated/api.schemas'
import { type EffectAxis, OUTCOMES, PLOT_WIDTHS, effectX, labelPlacement, signedPercent } from '../lib/results'

function share(value: number, axis: EffectAxis): string {
    return String(effectX(value, axis, 1))
}

export function BetEffectInterval({
    lower,
    upper,
    axis,
    outcome,
}: {
    lower: number
    upper: number
    axis: EffectAxis
    outcome: IdeaOutcomeEnumApi
}): JSX.Element {
    const label = `${signedPercent(lower)} to ${signedPercent(upper)}`
    const wide = labelPlacement(lower, upper, axis, PLOT_WIDTHS.wide, label)
    const narrow = labelPlacement(lower, upper, axis, PLOT_WIDTHS.narrow, label)
    const style = {
        '--interval-lower': share(lower, axis),
        '--interval-upper': share(upper, axis),
        '--interval-middle': share((lower + upper) / 2, axis),
        '--interval-tone': OUTCOMES[outcome].tone,
    } as CSSProperties
    return (
        <div
            className="BetEffectInterval"
            style={style}
            data-colored={outcome === 'won' || outcome === 'lost' || undefined}
            data-wide={wide.side}
            data-narrow={narrow.side}
            data-wide-cross={wide.crossesZero || undefined}
            data-narrow-cross={narrow.crossesZero || undefined}
            aria-label={`Change in the goal: ${label}`}
        >
            <span className="BetEffectInterval__line" />
            <span className="BetEffectInterval__dot" />
            <span className="BetEffectInterval__label tabular-nums">{label}</span>
        </div>
    )
}
