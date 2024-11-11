import { IconInfo } from '@posthog/icons'
import { LemonBanner, LemonInput, Link, Tooltip } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { humanFriendlyNumber } from 'lib/utils'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { Query } from '~/queries/Query/Query'
import { ExperimentIdType, InsightType } from '~/types'

import { MetricInsightId } from '../constants'
import { experimentLogic } from '../experimentLogic'
interface ExperimentCalculatorProps {
    experimentId: ExperimentIdType
}

function FunnelCalculation({ experimentId }: ExperimentCalculatorProps): JSX.Element {
    const {
        minimumDetectableEffect,
        experiment,
        conversionMetrics,
        minimumSampleSizePerVariant,
        recommendedRunningTime,
        variants,
    } = useValues(experimentLogic({ experimentId }))

    const funnelConversionRate = conversionMetrics?.totalRate * 100 || 0
    const conversionRate = conversionMetrics.totalRate * 100
    const sampleSizePerVariant = minimumSampleSizePerVariant(conversionRate)
    const funnelSampleSize = sampleSizePerVariant * variants.length

    // Displayed values
    const baselineConversionRate = funnelConversionRate.toFixed(1)
    const minimumAcceptableConversionRate = (funnelConversionRate + (minimumDetectableEffect || 5)).toFixed(1)
    const recommendedSampleSize = humanFriendlyNumber(funnelSampleSize || 0)

    return (
        <div className="flex flex-wrap">
            {!experiment?.start_date && (
                <>
                    <div className="mb-4 w-1/2">
                        <div className="card-secondary">Baseline Conversion Rate</div>
                        <div className="l4">{baselineConversionRate}%</div>
                    </div>
                    <div className="mb-4 w-1/2">
                        <div className="card-secondary">Minimum Acceptable Conversion Rate</div>
                        <div className="l4">{minimumAcceptableConversionRate}%</div>
                    </div>
                </>
            )}
            <div className="w-1/2">
                <div className="card-secondary">Recommended Sample Size</div>
                <div className="pb-4">
                    <span className="l4">~{recommendedSampleSize}</span> persons
                </div>
            </div>
            {!experiment?.start_date && (
                <div className="w-1/2">
                    <div className="card-secondary">Recommended running time</div>
                    <div>
                        <span className="l4">~{recommendedRunningTime}</span> days
                    </div>
                </div>
            )}
        </div>
    )
}

function TrendCalculation({ experimentId }: ExperimentCalculatorProps): JSX.Element {
    const { minimumDetectableEffect, experiment, trendResults, recommendedExposureForCountData } = useValues(
        experimentLogic({ experimentId })
    )

    const trendCount = trendResults[0]?.count || 0
    const trendExposure = recommendedExposureForCountData(trendCount)

    // Displayed values
    const baselineCount = humanFriendlyNumber(trendCount || 0)
    const minimumAcceptableCount = humanFriendlyNumber(
        trendCount + Math.ceil(trendCount * ((minimumDetectableEffect || 5) / 100)) || 0
    )
    const recommendedRunningTime = humanFriendlyNumber(trendExposure || 0)

    return (
        <div className="flex flex-wrap">
            {!experiment?.start_date && (
                <>
                    <div className="mb-4 w-1/2">
                        <div className="card-secondary">Baseline Count</div>
                        <div className="l4">{baselineCount}</div>
                    </div>
                    <div className="mb-4 w-1/2">
                        <div className="card-secondary">Minimum Acceptable Count</div>
                        <div className="l4">{minimumAcceptableCount}</div>
                    </div>
                </>
            )}
            <div className="w-1/2">
                <div className="card-secondary">Recommended running time</div>
                <div>
                    <span className="l4">~{recommendedRunningTime}</span> days
                </div>
            </div>
        </div>
    )
}

export function DataCollectionCalculator({ experimentId }: ExperimentCalculatorProps): JSX.Element {
    const { getMetricType, minimumDetectableEffect, experiment, conversionMetrics } = useValues(
        experimentLogic({ experimentId })
    )
    const { setExperiment } = useActions(experimentLogic({ experimentId }))

    const metricType = getMetricType(0)

    // :KLUDGE: need these to mount the Query component to load the insight */
    const insightLogicInstance = insightLogic({
        dashboardItemId: metricType === InsightType.FUNNELS ? MetricInsightId.Funnels : MetricInsightId.Trends,
        syncWithUrl: false,
    })
    const { insightProps } = useValues(insightLogicInstance)
    const { query } = useValues(insightDataLogic(insightProps))

    const funnelConversionRate = conversionMetrics?.totalRate * 100 || 0

    let sliderMaxValue = 0
    if (metricType === InsightType.FUNNELS) {
        if (100 - funnelConversionRate < 50) {
            sliderMaxValue = 100 - funnelConversionRate
        } else {
            sliderMaxValue = 50
        }
    } else {
        sliderMaxValue = 100
    }

    return (
        <div className="flex">
            <div className="w-full">
                <div className="mb-4 experiment-preview-row">
                    <div className="flex items-center">
                        <b>Minimum detectable effect</b>
                        <Tooltip
                            title={
                                <div className="space-y-2">
                                    <div>
                                        The Minimum detectable effect represents the smallest change that you want to be
                                        able to detect in your experiment.
                                    </div>
                                    <div>
                                        To make things easier, we initially set this value to a reasonable default.
                                        However, we encourage you to review and adjust it based on your specific goals.
                                    </div>
                                    <div>
                                        Read more in the{' '}
                                        <Link to="https://posthog.com/docs/experiments/sample-size-running-time#minimum-detectable-effect-mde">
                                            documentation.
                                        </Link>
                                    </div>
                                </div>
                            }
                            closeDelayMs={200}
                        >
                            <IconInfo className="text-muted-alt text-base ml-1" />
                        </Tooltip>
                    </div>
                    <div className="flex gap-4">
                        <LemonSlider
                            value={minimumDetectableEffect}
                            min={1}
                            max={sliderMaxValue}
                            step={1}
                            onChange={(value) => {
                                setExperiment({
                                    parameters: {
                                        ...experiment.parameters,
                                        minimum_detectable_effect: value,
                                    },
                                })
                            }}
                            className="w-5/6"
                        />
                        <LemonInput
                            className="w-1/6"
                            data-attr="min-detectable-effect"
                            type="number"
                            min={1}
                            max={sliderMaxValue}
                            defaultValue={5}
                            suffix={<span>%</span>}
                            value={minimumDetectableEffect}
                            onChange={(value) => {
                                if (value) {
                                    setExperiment({
                                        parameters: {
                                            ...experiment.parameters,
                                            minimum_detectable_effect: value,
                                        },
                                    })
                                }
                            }}
                        />
                    </div>
                </div>
                <div className="flex flex-col experiment-preview-row">
                    <LemonBanner type="info" className="mb-4">
                        The calculations are based on the events received in the last 14 days. This event count may
                        differ from what was considered in earlier estimates.
                    </LemonBanner>
                    {getMetricType(0) === InsightType.TRENDS ? (
                        <TrendCalculation experimentId={experimentId} />
                    ) : (
                        <FunnelCalculation experimentId={experimentId} />
                    )}
                    {/* :KLUDGE: mounting the query component to ensure the goal insight is loaded for the calculations */}
                    <div className="hidden">
                        <BindLogic logic={insightLogic} props={insightProps}>
                            <Query query={query} context={{ insightProps }} readOnly />
                        </BindLogic>
                    </div>
                </div>
            </div>
        </div>
    )
}
