import { IconInfo } from '@posthog/icons'
import { LemonInput, Tooltip } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { humanFriendlyNumber } from 'lib/utils'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { Query } from '~/queries/Query/Query'
import { InsightType } from '~/types'

import { EXPERIMENT_INSIGHT_ID } from '../constants'
import { experimentLogic } from '../experimentLogic'

interface ExperimentPreviewProps {
    experimentId: number | 'new'
}

export function DataCollectionCalculator({ experimentId }: ExperimentPreviewProps): JSX.Element {
    const {
        experimentInsightType,
        minimumDetectableChange,
        expectedRunningTime,
        experiment,
        trendResults,
        funnelResults,
        conversionMetrics,
        minimumSampleSizePerVariant,
        variants,
        recommendedExposureForCountData,
    } = useValues(experimentLogic({ experimentId }))
    const { setExperiment } = useActions(experimentLogic({ experimentId }))

    const insightLogicInstance = insightLogic({ dashboardItemId: EXPERIMENT_INSIGHT_ID, syncWithUrl: false })
    const { insightProps } = useValues(insightLogicInstance)
    const { query } = useValues(insightDataLogic(insightProps))

    const trendCount = trendResults[0]?.count || 0
    const trendExposure = recommendedExposureForCountData(trendCount)
    const funnelConversionRate = conversionMetrics?.totalRate * 100 || 0

    const sliderMaxValue =
        experimentInsightType === InsightType.FUNNELS
            ? 100 - funnelConversionRate < 50
                ? 100 - funnelConversionRate
                : 50
            : 50

    const currentDuration = dayjs().diff(dayjs(experiment?.start_date), 'hour')

    const funnelEntrants = funnelResults?.[0]?.count

    // SAMPLE SIZE & RUNNING TIME
    const conversionRate = conversionMetrics.totalRate * 100
    const sampleSizePerVariant = minimumSampleSizePerVariant(conversionRate)
    const funnelSampleSize = sampleSizePerVariant * variants.length
    let runningTime = 0
    if (experiment?.start_date) {
        runningTime = expectedRunningTime(funnelEntrants || 1, funnelSampleSize || 0, currentDuration)
    } else {
        runningTime = expectedRunningTime(funnelEntrants || 1, funnelSampleSize || 0)
    }

    return (
        <div className="flex">
            <div className="w-full">
                <div className="mb-4 experiment-preview-row">
                    <div className="flex items-center">
                        <b>Minimum acceptable improvement</b>
                        <Tooltip title="Minimum acceptable improvement is a calculation that estimates the smallest significant improvement you are willing to accept.">
                            <IconInfo className="ml-1 text-muted text-xl" />
                        </Tooltip>
                    </div>
                    <div className="flex gap-4">
                        <LemonSlider
                            value={minimumDetectableChange}
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
                            data-attr="min-acceptable-improvement"
                            type="number"
                            min={1}
                            max={sliderMaxValue}
                            defaultValue={5}
                            suffix={<span>%</span>}
                            value={minimumDetectableChange}
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
                    {experimentInsightType === InsightType.TRENDS ? (
                        <div className="flex flex-wrap">
                            {!experiment?.start_date && (
                                <>
                                    <div className="mb-4 w-1/2">
                                        <div className="card-secondary">Baseline Count</div>
                                        <div className="l4">{humanFriendlyNumber(trendCount || 0)}</div>
                                    </div>
                                    <div className="mb-4 w-1/2">
                                        <div className="card-secondary">Minimum Acceptable Count</div>
                                        <div className="l4">
                                            {humanFriendlyNumber(
                                                trendCount +
                                                    Math.ceil(trendCount * ((minimumDetectableChange || 5) / 100)) || 0
                                            )}
                                        </div>
                                    </div>
                                </>
                            )}
                            <div className="w-1/2">
                                <div className="card-secondary">Recommended running time</div>
                                <div>
                                    <span className="l4">~{humanFriendlyNumber(trendExposure || 0)}</span> days
                                </div>
                            </div>
                        </div>
                    ) : (
                        <div className="flex flex-wrap">
                            {!experiment?.start_date && (
                                <>
                                    <div className="mb-4 w-1/2">
                                        <div className="card-secondary">Baseline Conversion Rate</div>
                                        <div className="l4">{funnelConversionRate.toFixed(1)}%</div>
                                    </div>
                                    <div className="mb-4 w-1/2">
                                        <div className="card-secondary">Minimum Acceptable Conversion Rate</div>
                                        <div className="l4">
                                            {(funnelConversionRate + (minimumDetectableChange || 5)).toFixed(1)}%
                                        </div>
                                    </div>
                                </>
                            )}
                            <div className="w-1/2">
                                <div className="card-secondary">Recommended Sample Size</div>
                                <div className="pb-4">
                                    <span className="l4">~{humanFriendlyNumber(funnelSampleSize || 0)}</span> persons
                                </div>
                            </div>
                            {!experiment?.start_date && (
                                <div className="w-1/2">
                                    <div className="card-secondary">Recommended running time</div>
                                    <div>
                                        <span className="l4">~{humanFriendlyNumber(runningTime || 0)}</span> days
                                    </div>
                                </div>
                            )}
                        </div>
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
