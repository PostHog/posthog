import clsx from 'clsx'
import { useValues } from 'kea'

import { IconMinus, IconTrending } from '@posthog/icons'
import { LemonTagType, Tooltip } from '@posthog/lemon-ui'

import { experimentLogic } from '../../experimentLogic'

interface SignificanceHighlightProps {
    displayOrder?: number
    metricUuid?: string
    isSecondary?: boolean
    className?: string
}

export function SignificanceHighlight({
    displayOrder = 0,
    metricUuid,
    isSecondary = false,
    className = '',
}: SignificanceHighlightProps): JSX.Element {
    const { isPrimaryMetricSignificant, isSecondaryMetricSignificant, significanceDetails, experiment } =
        useValues(experimentLogic)

    // Convert displayOrder to UUID if UUID not provided
    let identifier = metricUuid
    if (!identifier) {
        const metrics = isSecondary ? experiment.metrics_secondary : experiment.metrics
        identifier = metrics[displayOrder]?.uuid || ''
    }

    if (!identifier) {
        return <div className={className} />
    }

    const isSignificant = isSecondary
        ? isSecondaryMetricSignificant(identifier)
        : isPrimaryMetricSignificant(identifier)
    const result: { color: LemonTagType; label: string } = isSignificant
        ? { color: 'success', label: 'Significant' }
        : { color: 'primary', label: 'Not significant' }

    const inner = isSignificant ? (
        <div className="bg-success-highlight text-success-light px-1.5 py-0.5 flex items-center gap-1 rounded border border-success-light">
            <IconTrending fontSize={20} fontWeight={600} />
            <span className="text-xs font-semibold">{result.label}</span>
        </div>
    ) : (
        <div className="bg-warning-highlight text-warning-dark px-1.5 py-0.5 flex items-center gap-1 rounded border border-warning">
            <IconMinus fontSize={20} fontWeight={600} />
            <span className="text-xs font-semibold">{result.label}</span>
        </div>
    )

    const details = significanceDetails(identifier)

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
