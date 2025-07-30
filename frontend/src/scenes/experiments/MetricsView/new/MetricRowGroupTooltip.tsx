import { LemonTag } from 'lib/lemon-ui/LemonTag'
import {
    formatChanceToWin,
    formatPValue,
    getIntervalLabel,
    getVariantInterval,
    isBayesianResult,
    type ExperimentVariantResult,
} from '../shared/utils'

export const renderTooltipContent = (variantResult: ExperimentVariantResult): JSX.Element => {
    const interval = getVariantInterval(variantResult)
    const [lower, upper] = interval ? [interval[0], interval[1]] : [0, 0]
    const intervalPercent = interval ? `[${(lower * 100).toFixed(2)}%, ${(upper * 100).toFixed(2)}%]` : 'N/A'
    const intervalLabel = getIntervalLabel(variantResult)

    return (
        <div className="flex flex-col gap-1">
            <div className="flex justify-between items-center">
                <div className="font-semibold">{variantResult.key}</div>
                {variantResult.key !== 'control' && (
                    <LemonTag
                        type={
                            !variantResult.significant
                                ? 'muted'
                                : (() => {
                                      const interval = getVariantInterval(variantResult)
                                      const deltaPercent = interval ? ((interval[0] + interval[1]) / 2) * 100 : 0
                                      return deltaPercent > 0 ? 'success' : 'danger'
                                  })()
                        }
                        size="medium"
                    >
                        {!variantResult.significant
                            ? 'Not significant'
                            : (() => {
                                  const interval = getVariantInterval(variantResult)
                                  const deltaPercent = interval ? ((interval[0] + interval[1]) / 2) * 100 : 0
                                  return deltaPercent > 0 ? 'Won' : 'Lost'
                              })()}
                    </LemonTag>
                )}
            </div>

            <div className="flex justify-between items-center">
                <span className="text-muted-alt font-semibold">Total value:</span>
                <span className="font-semibold">{variantResult.sum}</span>
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
                        (() => {
                            const deltaPercent = interval ? ((lower + upper) / 2) * 100 : 0
                            const isPositive = deltaPercent > 0
                            return (
                                <span className={isPositive ? 'text-success' : 'text-danger'}>
                                    {`${isPositive ? '+' : ''}${deltaPercent.toFixed(2)}%`}
                                </span>
                            )
                        })()
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
