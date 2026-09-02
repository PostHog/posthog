import './ConversionPaths.scss'

import clsx from 'clsx'

import { Tooltip } from '@posthog/lemon-ui'

/**
 * Collapse consecutive repeats for display: ['google', 'google', 'direct'] becomes google ×2 → direct.
 * The backend deliberately returns the raw sequence — two google visits are a different journey than
 * one — so the ×N is purely how that journey reads on screen.
 */
export function collapseConsecutive(path: string[]): { value: string; count: number }[] {
    const collapsed: { value: string; count: number }[] = []
    for (const value of path) {
        const last = collapsed[collapsed.length - 1]
        if (last && last.value === value) {
            last.count += 1
        } else {
            collapsed.push({ value, count: 1 })
        }
    }
    return collapsed
}

export function ConversionPathChips({
    path,
    truncated,
    colorFor,
}: {
    path: string[]
    truncated: boolean
    /** Deterministic color per breakdown value, so "google" reads as the same hue on every row. */
    colorFor: (value: string) => string
}): JSX.Element {
    const steps = collapseConsecutive(path)

    return (
        <ol className="ConversionPaths__path">
            {truncated && (
                <Tooltip title="This journey started earlier — showing its most recent touchpoints.">
                    <li className="ConversionPaths__chip ConversionPaths__chip--overflow">…</li>
                </Tooltip>
            )}
            {steps.map((step, index) => {
                const first = index === 0 && !truncated
                const last = index === steps.length - 1
                return (
                    <li
                        key={index}
                        className={clsx('ConversionPaths__chip', {
                            'ConversionPaths__chip--first': first && !last,
                            'ConversionPaths__chip--last': last && !first,
                            'ConversionPaths__chip--only': first && last,
                        })}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={
                            {
                                '--path-chip-color': colorFor(step.value),
                            } as React.CSSProperties
                        }
                    >
                        {step.value || <span className="text-secondary">(none)</span>}
                        {step.count > 1 && <span className="ConversionPaths__chip-count">×{step.count}</span>}
                    </li>
                )
            })}
        </ol>
    )
}
