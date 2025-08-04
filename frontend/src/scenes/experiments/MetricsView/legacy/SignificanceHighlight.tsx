import { IconMinus, IconTrending } from '@posthog/icons'
import { LemonTagType, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useValues } from 'kea'

import { experimentLogic } from '../../experimentLogic'

interface SignificanceHighlightProps {
    metricIndex?: number
    isSecondary?: boolean
    className?: string
}

export function SignificanceHighlight({
    metricIndex = 0,
    isSecondary = false,
    className = '',
}: SignificanceHighlightProps): JSX.Element {
    const { isPrimaryMetricSignificant, isSecondaryMetricSignificant, significanceDetails } = useValues(experimentLogic)
    const isSignificant = isSecondary
        ? isSecondaryMetricSignificant(metricIndex)
        : isPrimaryMetricSignificant(metricIndex)
    const result: { color: LemonTagType; label: string } = isSignificant
        ? { color: 'success', label: 'Significant' }
        : { color: 'primary', label: 'Not significant' }

    const inner = isSignificant ? (
        <div className="bg-success-highlight text-success-foreground-light px-1.5 py-0.5 flex items-center gap-1 rounded border border-success-light">
            <IconTrending fontSize={20} fontWeight={600} />
            <span className="text-xs font-semibold">{result.label}</span>
        </div>
    ) : (
        <div className="bg-warning-highlight text-warning-foreground-dark px-1.5 py-0.5 flex items-center gap-1 rounded border border-warning">
            <IconMinus fontSize={20} fontWeight={600} />
            <span className="text-xs font-semibold">{result.label}</span>
        </div>
    )

    const details = significanceDetails(metricIndex)

    return details ? (
        <Tooltip title={details}>
            <div
                className={clsx({
                    'cursor-default': true,
                    'bg-[var(--color-bg-table)]': true,
                    [className]: true,
                })}
            >
                {inner}
            </div>
        </Tooltip>
    ) : (
        <div className={clsx({ 'bg-[var(--color-bg-table)]': true, [className]: true })}>{inner}</div>
    )
}
