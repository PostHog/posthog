import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput, LemonModal, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import { InsightLabel } from 'lib/components/InsightLabel'
import { PropertyFilterButton } from 'lib/components/PropertyFilters/components/PropertyFilterButton'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { humanFriendlyNumber } from 'lib/utils'
import { groupFilters } from 'scenes/feature-flags/FeatureFlags'
import { urls } from 'scenes/urls'

import {
    ActionFilter as ActionFilterType,
    AnyPropertyFilter,
    FilterType,
    InsightType,
    MultivariateFlagVariant,
} from '~/types'

import { EXPERIMENT_EXPOSURE_INSIGHT_ID, EXPERIMENT_INSIGHT_ID } from './constants'
import { experimentLogic } from './experimentLogic'
import { ExperimentWorkflow } from './ExperimentWorkflow'
import { MetricSelector } from './MetricSelector'

interface ExperimentPreviewProps {
    experimentId: number | 'new'
    trendCount: number
    trendExposure?: number
    funnelSampleSize?: number
    funnelConversionRate: number
    funnelEntrants?: number
}

export function ExperimentPreview({
    experimentId,
    trendCount,
    funnelConversionRate,
    trendExposure,
    funnelSampleSize,
    funnelEntrants,
}: ExperimentPreviewProps): JSX.Element {
    const {
        experimentInsightType,
        editingExistingExperiment,
        minimumDetectableEffect,
        expectedRunningTime,
        aggregationLabel,
        experiment,
        isExperimentGoalModalOpen,
        isExperimentExposureModalOpen,
        experimentLoading,
        experimentMathAggregationForTrends,
    } = useValues(experimentLogic({ experimentId }))
    const {
        setExperiment,
        openExperimentGoalModal,
        closeExperimentGoalModal,
        updateExperimentGoal,
        openExperimentExposureModal,
        closeExperimentExposureModal,
        updateExperimentExposure,
        setNewExperimentInsight,
        setExperimentExposureInsight,
    } = useActions(experimentLogic({ experimentId }))
    const sliderMaxValue =
        experimentInsightType === InsightType.FUNNELS
            ? 100 - funnelConversionRate < 50
                ? 100 - funnelConversionRate
                : 50
            : 50

    const currentDuration = dayjs().diff(dayjs(experiment?.start_date), 'hour')

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
            <div
                className={
                    !experiment?.start_date && experimentId !== 'new' && !editingExistingExperiment ? 'w-1/2' : 'w-full'
                }
            >
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
                {(experimentId === 'new' || editingExistingExperiment) && (
                    <div className="mb-4 experiment-preview-row">
                        <div className="flex items-center">
                            <b>Minimum detectable effect</b>
                            <Tooltip title="Minimum detectable effect is a calculation that estimates the smallest significant improvement you are willing to accept.">
                                <IconInfo className="ml-1 text-muted text-xl" />
                            </Tooltip>
                        </div>
                        <div className="flex gap-2">
                            <LemonSlider
                                value={experiment.parameters.minimum_detectable_effect ?? 5}
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
                                className="w-1/3"
                            />
                            <LemonInput
                                data-attr="min-detectable-effect"
                                type="number"
                                min={1}
                                max={sliderMaxValue}
                                defaultValue={5}
                                suffix={<span>%</span>}
                                value={experiment.parameters.minimum_detectable_effect || 5}
                                onChange={(value) => {
                                    setExperiment({
                                        parameters: {
                                            ...experiment.parameters,
                                            minimum_detectable_effect: value ?? undefined,
                                        },
                                    })
                                }}
                            />
                        </div>
                    </div>
                )}
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
                                                    Math.ceil(trendCount * ((minimumDetectableEffect || 5) / 100)) || 0
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
                                            {(funnelConversionRate + (minimumDetectableEffect || 5)).toFixed(1)}%
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
                {experimentId !== 'new' && !editingExistingExperiment && (
                    <div className="experiment-preview-row">
                        <div className="card-secondary mb-2">
                            {experimentInsightType === InsightType.FUNNELS ? 'Conversion goal steps' : 'Trend goal'}
                        </div>
                        <MetricDisplay filters={experiment.filters} />
                        {experiment?.start_date && (
                            <>
                                <div className="mb-2 mt-4">
                                    <LemonButton type="secondary" onClick={openExperimentGoalModal}>
                                        Change experiment goal
                                    </LemonButton>
                                </div>
                                {experimentInsightType === InsightType.TRENDS &&
                                    !experimentMathAggregationForTrends(experiment.filters) && (
                                        <>
                                            <div className="card-secondary mb-2 mt-4">
                                                Exposure metric
                                                <Tooltip
                                                    title={`This metric determines how we calculate exposure for the experiment. Only users who have this event alongside the property '$feature/${experiment.feature_flag_key}' are included in exposure calculations.`}
                                                >
                                                    <IconInfo className="ml-1 text-muted text-sm" />
                                                </Tooltip>
                                            </div>
                                            {experiment.parameters?.custom_exposure_filter ? (
                                                <MetricDisplay filters={experiment.parameters.custom_exposure_filter} />
                                            ) : (
                                                <span className="description">
                                                    Default via $feature_flag_called events
                                                </span>
                                            )}
                                            <div className="mb-2 mt-2">
                                                <span className="flex">
                                                    <LemonButton
                                                        type="secondary"
                                                        size="small"
                                                        onClick={openExperimentExposureModal}
                                                        className="mr-2"
                                                    >
                                                        Change exposure metric
                                                    </LemonButton>
                                                    {experiment.parameters?.custom_exposure_filter && (
                                                        <LemonButton
                                                            type="secondary"
                                                            status="danger"
                                                            size="small"
                                                            className="mr-2"
                                                            onClick={() => updateExperimentExposure(null)}
                                                        >
                                                            Reset exposure
                                                        </LemonButton>
                                                    )}
                                                </span>
                                            </div>
                                        </>
                                    )}
                            </>
                        )}
                    </div>
                )}
            </div>

            {experimentId !== 'new' && !editingExistingExperiment && !experiment?.start_date && (
                <div className="w-1/2 pl-4">
                    <ExperimentWorkflow />
                </div>
            )}
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

export function MetricDisplay({ filters }: { filters?: FilterType }): JSX.Element {
    const experimentInsightType = filters?.insight || InsightType.TRENDS

    return (
        <>
            {([...(filters?.events || []), ...(filters?.actions || [])] as ActionFilterType[])
                .sort((a, b) => (a.order || 0) - (b.order || 0))
                .map((event: ActionFilterType, idx: number) => (
                    <div key={idx} className="mb-2">
                        <div className="flex mb-1">
                            <div className="shrink-0 w-6 h-6 mr-2 font-bold text-center text-primary-alt bg-light border rounded">
                                {experimentInsightType === InsightType.FUNNELS ? (event.order || 0) + 1 : idx + 1}
                            </div>
                            <b>
                                <InsightLabel
                                    action={event}
                                    showCountedByTag={experimentInsightType === InsightType.TRENDS}
                                    hideIcon
                                    showEventName
                                />
                            </b>
                        </div>
                        <div className="space-y-1">
                            {event.properties?.map((prop: AnyPropertyFilter) => (
                                <PropertyFilterButton key={prop.key} item={prop} />
                            ))}
                        </div>
                    </div>
                ))}
        </>
    )
}
