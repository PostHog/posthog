import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { humanFriendlyNumber } from 'lib/utils'
import {
    formatChanceToWin,
    formatPValue,
    getIntervalLabel,
    formatIntervalPercent,
    isSignificant,
    isDeltaPositive,
    formatDeltaPercent,
    isBayesianResult,
    type ExperimentVariantResult,
} from '../shared/utils'

export const renderTooltipContent = (variantResult: ExperimentVariantResult): JSX.Element => {
    const intervalPercent = formatIntervalPercent(variantResult)
    const intervalLabel = getIntervalLabel(variantResult)
    const significant = isSignificant(variantResult)
    const deltaPositive = isDeltaPositive(variantResult)

    return (
        <div className="flex flex-col gap-1">
            <div className="flex justify-between items-center">
                <div className="font-semibold pb-2">{variantResult.key}</div>
                {variantResult.key !== 'control' && (
                    <LemonTag type={!significant ? 'muted' : deltaPositive ? 'success' : 'danger'} size="medium">
                        {!significant ? 'Not significant' : deltaPositive ? 'Won' : 'Lost'}
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
                    <span className="font-semibold">{formatChanceToWin(variantResult.chance_to_win)}</span>
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
                        <span className={deltaPositive ? 'text-success' : 'text-danger'}>
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
