import clsx from 'clsx'
import { useValues } from 'kea'

import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { EXPERIMENT_VARIANT_MULTIPLE } from 'scenes/experiments/constants'
import { getVariantColor } from 'scenes/experiments/utils'

import { legacyExperimentLogic } from '~/scenes/experiments/legacy'

/**
 * @deprecated
 * Legacy variant tag component.
 * Frozen copy for legacy experiments - do not modify.
 */
export function LegacyVariantTag({
    variantKey,
    fontSize,
    className,
}: {
    variantKey: string
    fontSize?: number
    className?: string
}): JSX.Element {
    const { experiment, legacyPrimaryMetricsResults } = useValues(legacyExperimentLogic)

    if (variantKey === EXPERIMENT_VARIANT_MULTIPLE) {
        return (
            <Tooltip title="Some users were exposed to more than one variant. If this percentage is high, there may be an implementation issue causing inconsistent variant assignment.">
                <LemonTag type="danger">{variantKey}</LemonTag>
            </Tooltip>
        )
    }

    if (!legacyPrimaryMetricsResults) {
        return <></>
    }

    const variantColor = experiment.feature_flag?.filters.multivariate?.variants
        ? getVariantColor(variantKey, experiment.feature_flag?.filters.multivariate?.variants)
        : 'var(--text-muted)'

    if (experiment.holdout && variantKey === `holdout-${experiment.holdout_id}`) {
        return (
            <span className={clsx('flex items-center min-w-0', className)}>
                <div
                    className="w-2 h-2 rounded-full shrink-0"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        backgroundColor: variantColor,
                    }}
                />
                <LemonTag type="option" className="ml-2">
                    {experiment.holdout.name}
                </LemonTag>
            </span>
        )
    }

    return (
        <span className={clsx('flex items-center min-w-0', className)}>
            <span
                className="ml-2 text-xs font-semibold truncate text-secondary"
                // eslint-disable-next-line react/forbid-dom-props
                style={fontSize ? { fontSize: `${fontSize}px` } : undefined}
            >
                {variantKey}
            </span>
        </span>
    )
}
