import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { humanFriendlyNumber } from 'lib/utils'

import { InsightType, TrendExperimentVariant } from '~/types'

import { VariantTag } from '../../ExperimentView/components'
import { calculateDelta } from '../../legacyExperimentCalculations'

interface VariantTooltipProps {
    tooltipData: {
        x: number
        y: number
        variant: string
    }
    result: any
    metricType: InsightType
    conversionRateForVariant: (result: any, variant: string) => any
    countDataForVariant: (result: any, variant: string) => any
    exposureCountDataForVariant: (result: any, variant: string) => any
    credibleIntervalForVariant: (result: any, variant: string, metricType: InsightType) => any
}

export function VariantTooltip({
    tooltipData,
    result,
    metricType,
    conversionRateForVariant,
    countDataForVariant,
    exposureCountDataForVariant,
    credibleIntervalForVariant,
}: VariantTooltipProps): JSX.Element {
    return (
        <div
            className="fixed -translate-x-1/2 -translate-y-full bg-[var(--color-bg-surface-primary)] border border-[var(--color-border-primary)] px-3 py-2 rounded-md text-[13px] shadow-md pointer-events-none z-[103] min-w-[300px]"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                left: tooltipData.x,
                top: tooltipData.y,
            }} // Dynamic positioning based on mouse hover position
        >
            <div className="flex flex-col gap-1">
                <VariantTag variantKey={tooltipData.variant} />
                <div className="inline-flex">
                    <span className="text-secondary font-semibold mb-1">Win probability:</span>
                    {result?.probability?.[tooltipData.variant] !== undefined ? (
                        <span className="flex items-center justify-between flex-1 pl-6">
                            <LemonProgress
                                className="w-3/4 mr-4"
                                percent={result.probability[tooltipData.variant] * 100}
                            />
                            <span className="font-semibold">
                                {(result.probability[tooltipData.variant] * 100).toFixed(2)}%
                            </span>
                        </span>
                    ) : (
                        <span>—</span>
                    )}
                </div>
                {metricType === InsightType.TRENDS ? (
                    <>
                        <div className="flex justify-between items-center">
                            <span className="text-secondary font-semibold">
                                {metricType === InsightType.TRENDS && result.exposure_query?.series?.[0]?.math ? (
                                    <span>Total</span>
                                ) : (
                                    <span>Count</span>
                                )}
                                <span>:</span>
                            </span>
                            <span className="font-semibold">
                                {(() => {
                                    const count = countDataForVariant(result, tooltipData.variant)
                                    return count !== null ? humanFriendlyNumber(count) : <span>—</span>
                                })()}
                            </span>
                        </div>
                        <div className="flex justify-between items-center">
                            <span className="text-secondary font-semibold">Exposure:</span>
                            <span className="font-semibold">
                                {(() => {
                                    const exposure = exposureCountDataForVariant(result, tooltipData.variant)
                                    return exposure !== null ? humanFriendlyNumber(exposure) : '—'
                                })()}
                            </span>
                        </div>
                        <div className="flex justify-between items-center">
                            <span className="text-secondary font-semibold">Mean:</span>
                            <span className="font-semibold">
                                {(() => {
                                    const variant = result.variants.find(
                                        (v: TrendExperimentVariant) => v.key === tooltipData.variant
                                    )
                                    return variant?.count && variant?.absolute_exposure
                                        ? (variant.count / variant.absolute_exposure).toFixed(2)
                                        : '—'
                                })()}
                            </span>
                        </div>
                    </>
                ) : (
                    <div className="flex justify-between items-center">
                        <span className="text-secondary font-semibold">Conversion rate:</span>
                        <span className="font-semibold">
                            {conversionRateForVariant(result, tooltipData.variant)?.toFixed(2)}%
                        </span>
                    </div>
                )}
                <div className="flex justify-between items-center">
                    <span className="text-secondary font-semibold">Delta:</span>
                    <span className="font-semibold">
                        {tooltipData.variant === 'control' ? (
                            <em className="text-secondary">Baseline</em>
                        ) : (
                            (() => {
                                const deltaResult = calculateDelta(result, tooltipData.variant, metricType)
                                if (!deltaResult) {
                                    return '—'
                                }

                                return (
                                    <span className={deltaResult.isPositive ? 'text-success' : 'text-danger'}>
                                        {`${deltaResult.isPositive ? '+' : ''}${deltaResult.deltaPercent.toFixed(2)}%`}
                                    </span>
                                )
                            })()
                        )}
                    </span>
                </div>
                <div className="flex justify-between items-center">
                    <span className="text-secondary font-semibold">Credible interval:</span>
                    <span className="font-semibold">
                        {(() => {
                            const interval = credibleIntervalForVariant(result, tooltipData.variant, metricType)
                            const [lower, upper] = interval ? [interval[0] / 100, interval[1] / 100] : [0, 0]
                            return `[${lower > 0 ? '+' : ''}${(lower * 100).toFixed(2)}%, ${upper > 0 ? '+' : ''}${(
                                upper * 100
                            ).toFixed(2)}%]`
                        })()}
                    </span>
                </div>
            </div>
        </div>
    )
}
