import clsx from 'clsx'
import { useValues } from 'kea'

import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { experimentLogic } from '~/scenes/experiments/experimentLogic'
import { getExperimentVariants, getVariantColor } from '~/scenes/experiments/utils'

import { EXPERIMENT_VARIANT_MULTIPLE } from 'products/experiments/frontend/constants'

import { MULTIPLE_VARIANT_HELP } from '../MetricsView/new/metricsTableCopy'

export function VariantTag({
    variantKey,
    fontSize,
    className,
}: {
    variantKey: string
    fontSize?: number
    className?: string
}): JSX.Element {
    const { experiment } = useValues(experimentLogic)

    if (variantKey === EXPERIMENT_VARIANT_MULTIPLE) {
        return (
            <Tooltip title={MULTIPLE_VARIANT_HELP}>
                <LemonTag type="danger">{variantKey}</LemonTag>
            </Tooltip>
        )
    }

    const variantColor = getVariantColor(variantKey, getExperimentVariants(experiment))

    /**
     * this is only used on the distribution table, to display the holdout name
     */
    if (experiment.holdout && variantKey === `holdout-${experiment.holdout_id}`) {
        return (
            <span className={clsx('flex items-center min-w-0', className)}>
                <LemonTag type="option" className="ml-2">
                    {experiment.holdout.name}
                </LemonTag>
            </span>
        )
    }

    return (
        <span className={clsx('flex items-center min-w-0', className)}>
            <div
                className="w-2 h-2 rounded-full shrink-0"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ backgroundColor: variantColor }}
            />
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
