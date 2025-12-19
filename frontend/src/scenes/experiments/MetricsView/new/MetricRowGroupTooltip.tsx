import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { humanFriendlyNumber } from 'lib/utils'
import { VariantTag } from 'scenes/experiments/ExperimentView/components'

import { ExperimentMetric } from '~/queries/schema/schema-general'

import {
    type ExperimentVariantResult,
    formatChanceToWinForGoal,
    formatDeltaPercent,
    formatIntervalPercent,
    formatPValue,
    getIntervalLabel,
    isBayesianResult,
    isSignificant,
    isWinning,
} from '../shared/utils'

export const renderTooltipContent = (variantResult: ExperimentVariantResult, metric: ExperimentMetric): JSX.Element => {
    const intervalPercent = formatIntervalPercent(variantResult)
    const intervalLabel = getIntervalLabel(variantResult)
    const significant = isSignificant(variantResult)

    const winning = isWinning(variantResult, metric.goal)

    return (
        <div className="flex flex-col gap-1">
            <div className="flex justify-between items-center">
                <VariantTag variantKey={variantResult.key} />
                {variantResult.key !== 'control' && (
                    <LemonTag type={!significant ? 'muted' : winning ? 'success' : 'danger'} size="medium">
                        {!significant ? 'Not significant' : winning ? 'Won' : 'Lost'}
                    </LemonTag>
                )}
            </div>

            <div className="flex justify-between items-center">
                <span className="text-muted-alt font-semibold">Total value:</span>
                <span className="font-semibold">{humanFriendlyNumber(variantResult.sum)}</span>
            </div>

            <div className="flex justify-between items-center">
                <span className="text-muted-alt font-semibold">Exposures:</span>
                <span className="font-semibold">{variantResult.number_of_samples}</span>
            </div>

            {isBayesianResult(variantResult) ? (
                <div className="flex justify-between items-center">
                    <span className="text-muted-alt font-semibold">Chance to win:</span>
                    <span className="font-semibold">{formatChanceToWinForGoal(variantResult, metric.goal)}</span>
                </div>
            ) : (
                <div className="flex justify-between items-center">
                    <span className="text-muted-alt font-semibold">P-value:</span>
                    <span className="font-semibold">{formatPValue(variantResult.p_value)}</span>
                </div>
            )}

            <div className="flex justify-between items-center">
                <span className="text-muted-alt font-semibold">Delta:</span>
                <span className="font-semibold">
                    {variantResult.key === 'control' ? (
                        <em className="text-muted-alt">Baseline</em>
                    ) : (
                        <span className={winning ? 'text-success' : 'text-danger'}>
                            {formatDeltaPercent(variantResult)}
                        </span>
                    )}
                </span>
            </div>

            <div className="flex justify-between items-center">
                <span className="text-muted-alt font-semibold">{intervalLabel}:</span>
                <span className="font-semibold">{intervalPercent}</span>
            </div>
        </div>
    )
}
