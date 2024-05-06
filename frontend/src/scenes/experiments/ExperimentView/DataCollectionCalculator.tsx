import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput, LemonModal, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { humanFriendlyNumber } from 'lib/utils'
import { groupFilters } from 'scenes/feature-flags/FeatureFlags'
import { urls } from 'scenes/urls'

import { InsightType, MultivariateFlagVariant } from '~/types'

import { EXPERIMENT_EXPOSURE_INSIGHT_ID, EXPERIMENT_INSIGHT_ID } from '../constants'
import { experimentLogic } from '../experimentLogic'
import { MetricSelector } from '../MetricSelector'

interface ExperimentPreviewProps {
    experimentId: number | 'new'
    trendExposure?: number
    funnelEntrants?: number
}

export function DataCollectionCalculator({
    experimentId,
    trendExposure,
    funnelEntrants,
}: ExperimentPreviewProps): JSX.Element {
    const {
        experimentInsightType,
        editingExistingExperiment,
        minimumDetectableChange,
        expectedRunningTime,
        aggregationLabel,
        experiment,
        isExperimentGoalModalOpen,
        isExperimentExposureModalOpen,
        experimentLoading,
        trendResults,
        conversionMetrics,
        minimumSampleSizePerVariant,
        variants,
    } = useValues(experimentLogic({ experimentId }))
    const {
        setExperiment,
        closeExperimentGoalModal,
        updateExperimentGoal,
        closeExperimentExposureModal,
        updateExperimentExposure,
        setNewExperimentInsight,
        setExperimentExposureInsight,
    } = useActions(experimentLogic({ experimentId }))

    const trendCount = trendResults[0]?.count || 0
    const funnelConversionRate = conversionMetrics?.totalRate * 100 || 0

    const sliderMaxValue =
        experimentInsightType === InsightType.FUNNELS
            ? 100 - funnelConversionRate < 50
                ? 100 - funnelConversionRate
                : 50
            : 50

    const currentDuration = dayjs().diff(dayjs(experiment?.start_date), 'hour')

    // SAMPLE SIZE & RUNNING TIME
    const conversionRate = conversionMetrics.totalRate * 100
    console.log(conversionMetrics)
    const sampleSizePerVariant = minimumSampleSizePerVariant(conversionRate)
    const funnelSampleSize = sampleSizePerVariant * variants.length
    let runningTime = 0
    if (experiment?.start_date) {
        runningTime = expectedRunningTime(funnelEntrants || 1, funnelSampleSize || 0, currentDuration)
    } else {
        runningTime = expectedRunningTime(funnelEntrants || 1, funnelSampleSize || 0)
    }

    const expectedEndDate = dayjs(experiment?.start_date).add(runningTime, 'hour')
    const showEndDate = !experiment?.end_date && currentDuration >= 24 && funnelEntrants && funnelSampleSize

    const targetingProperties = experiment.feature_flag?.filters

    return (
        <div className="flex">
            <div className="w-full">
                {experimentId === 'new' && (
                    <div>
                        <div>
                            <b>Experiment preview</b>
                        </div>
                        <div className="text-muted">
                            Here are the baseline metrics for your experiment. Adjust your minimum detectible threshold
                            to adjust for the smallest conversion value you'll accept, and the experiment duration.{' '}
                        </div>
                        <LemonDivider className="my-4" />
                    </div>
                )}
                <div className="mb-4 experiment-preview-row">
                    <div className="flex items-center">
                        <b>Minimum acceptable improvement</b>
                        <Tooltip title="Minimum acceptable improvement is a calculation that estimates the smallest significant improvement you are willing to accept.">
                            <IconInfo className="ml-1 text-muted text-xl" />
                        </Tooltip>
                    </div>
                    <div className="flex gap-2">
                        <LemonSlider
                            value={minimumDetectableChange}
                            min={1}
                            max={sliderMaxValue}
                            step={1}
                            onChange={(value) => {
                                // setTruthMinimumDetectableChange(value)

                                setExperiment({
                                    parameters: {
                                        ...experiment.parameters,
                                        minimum_detectable_effect: value,
                                    },
                                })
                                // setTimeout(() => {
                                //     console.log(experiment.parameters)
                                // }, 500)
                            }}
                            className="w-1/3"
                        />
                        <LemonInput
                            data-attr="min-acceptable-improvement"
                            type="number"
                            min={1}
                            max={sliderMaxValue}
                            defaultValue={5}
                            suffix={<span>%</span>}
                            value={minimumDetectableChange}
                            onChange={(value) => {
                                // if (value) {
                                //     setTruthMinimumDetectableChange(value)
                                // }
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
                        <div className="flex">
                            {!experiment?.start_date && (
                                <>
                                    <div className="w-1/4">
                                        <div className="card-secondary">Baseline Count</div>
                                        <div className="l4">{humanFriendlyNumber(trendCount || 0)}</div>
                                    </div>
                                    <div className="w-1/4">
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
                                    <div className="w-1/2">
                                        <div className="card-secondary">Baseline Conversion Rate</div>
                                        <div className="l4">{funnelConversionRate.toFixed(1)}%</div>
                                    </div>
                                    <div className="w-1/2">
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
                    <div className="flex w-full mt-4">
                        <div className="flex-1">
                            <div className="card-secondary">Experiment variants</div>
                            <ul className="variants-list">
                                {experiment?.parameters?.feature_flag_variants?.map(
                                    (variant: MultivariateFlagVariant, idx: number) => (
                                        <li key={idx}>{variant.key}</li>
                                    )
                                )}
                            </ul>
                        </div>
                        <div className="flex-1">
                            <div className="card-secondary">Participants</div>
                            <div className="inline-block">
                                {targetingProperties ? (
                                    <>
                                        {groupFilters(targetingProperties, undefined, aggregationLabel)}
                                        <LemonButton
                                            to={
                                                experiment.feature_flag
                                                    ? urls.featureFlag(experiment.feature_flag.id)
                                                    : undefined
                                            }
                                            size="small"
                                            className="mt-0.5"
                                            type="secondary"
                                            center
                                        >
                                            Check flag release conditions
                                        </LemonButton>
                                    </>
                                ) : (
                                    '100% of all users'
                                )}
                            </div>
                        </div>
                    </div>
                    <div className="flex w-full">
                        {experimentId !== 'new' && !editingExistingExperiment && (
                            <div className="w-1/2">
                                <div className="card-secondary mt-4">Start date</div>
                                {experiment?.start_date ? (
                                    <TZLabel time={experiment?.start_date} />
                                ) : (
                                    <span className="description">Not started yet</span>
                                )}
                            </div>
                        )}
                        {experimentInsightType === InsightType.FUNNELS && showEndDate ? (
                            <div className="w-1/2">
                                <div className="card-secondary mt-4">Expected end date</div>
                                <span>
                                    {expectedEndDate.isAfter(dayjs())
                                        ? expectedEndDate.format('D MMM YYYY')
                                        : dayjs().format('D MMM YYYY')}
                                </span>
                            </div>
                        ) : null}
                        {/* The null prevents showing a 0 while loading */}
                        {experiment?.end_date && (
                            <div className="w-1/2">
                                <div className="card-secondary mt-4">Completed date</div>
                                <TZLabel time={experiment?.end_date} />
                            </div>
                        )}
                    </div>
                </div>
            </div>
            <LemonModal
                isOpen={isExperimentGoalModalOpen}
                onClose={closeExperimentGoalModal}
                width={1000}
                title="Change experiment goal"
                footer={
                    <div className="flex items-center gap-2">
                        <LemonButton
                            form="edit-experiment-goal-form"
                            type="secondary"
                            onClick={closeExperimentGoalModal}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            form="edit-experiment-goal-form"
                            onClick={() => {
                                updateExperimentGoal(experiment.filters)
                            }}
                            type="primary"
                            loading={experimentLoading}
                            data-attr="create-annotation-submit"
                        >
                            Save
                        </LemonButton>
                    </div>
                }
            >
                <Form
                    logic={experimentLogic}
                    props={{ experimentId }}
                    formKey="experiment"
                    id="edit-experiment-goal-form"
                    className="space-y-4"
                >
                    <Field name="filters">
                        <MetricSelector
                            dashboardItemId={EXPERIMENT_INSIGHT_ID}
                            setPreviewInsight={setNewExperimentInsight}
                            showDateRangeBanner
                        />
                    </Field>
                </Form>
            </LemonModal>
            <LemonModal
                isOpen={isExperimentExposureModalOpen}
                onClose={closeExperimentExposureModal}
                width={1000}
                title="Change experiment exposure"
                footer={
                    <div className="flex items-center gap-2">
                        <LemonButton
                            form="edit-experiment-exposure-form"
                            type="secondary"
                            onClick={closeExperimentExposureModal}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            form="edit-experiment-exposure-form"
                            onClick={() => {
                                if (experiment.parameters.custom_exposure_filter) {
                                    updateExperimentExposure(experiment.parameters.custom_exposure_filter)
                                }
                            }}
                            type="primary"
                            loading={experimentLoading}
                            data-attr="create-annotation-submit"
                        >
                            Save
                        </LemonButton>
                    </div>
                }
            >
                <Form
                    logic={experimentLogic}
                    props={{ experimentId }}
                    formKey="experiment"
                    id="edit-experiment-exposure-form"
                    className="space-y-4"
                >
                    <Field name="filters">
                        <MetricSelector
                            dashboardItemId={EXPERIMENT_EXPOSURE_INSIGHT_ID}
                            setPreviewInsight={setExperimentExposureInsight}
                            forceTrendExposureMetric
                        />
                    </Field>
                </Form>
            </LemonModal>
        </div>
    )
}
