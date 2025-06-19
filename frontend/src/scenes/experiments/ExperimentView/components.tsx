import { IconFlask } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonDivider,
    LemonLabel,
    LemonModal,
    LemonSelect,
    LemonSkeleton,
    LemonTag,
    LemonTagType,
    LemonTextArea,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { InsightLabel } from 'lib/components/InsightLabel'
import { PageHeader } from 'lib/components/PageHeader'
import { PropertyFilterButton } from 'lib/components/PropertyFilters/components/PropertyFilterButton'
import { IconAreaChart } from 'lib/lemon-ui/icons'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LoadingBar } from 'lib/lemon-ui/LoadingBar'
import { useEffect, useState } from 'react'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'
import { Query } from '~/queries/Query/Query'
import {
    ExperimentFunnelsQueryResponse,
    ExperimentTrendsQueryResponse,
    FunnelsQuery,
    InsightQueryNode,
    InsightVizNode,
    NodeKind,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import {
    ActionFilter,
    AnyPropertyFilter,
    Experiment,
    Experiment as ExperimentType,
    ExperimentConclusion,
    ExperimentIdType,
    InsightShortId,
} from '~/types'

import { CONCLUSION_DISPLAY_CONFIG, EXPERIMENT_VARIANT_MULTIPLE } from '../constants'
import { getIndexForVariant } from '../experimentCalculations'
import { experimentLogic, FORM_MODES } from '../experimentLogic'
import { getExperimentStatus, getExperimentStatusColor } from '../experimentsLogic'
import { getExperimentInsightColour } from '../utils'

export function VariantTag({
    experimentId,
    variantKey,
    muted = false,
    fontSize,
    className,
}: {
    experimentId: ExperimentIdType
    variantKey: string
    muted?: boolean
    fontSize?: number
    className?: string
}): JSX.Element {
    const { experiment, legacyPrimaryMetricsResults, getInsightType } = useValues(experimentLogic({ experimentId }))

    if (variantKey === EXPERIMENT_VARIANT_MULTIPLE) {
        return (
            <Tooltip title="This indicates a potential implementation issue where users are seeing multiple variants instead of a single consistent variant.">
                <LemonTag type="danger">{variantKey}</LemonTag>
            </Tooltip>
        )
    }

    if (!legacyPrimaryMetricsResults) {
        return <></>
    }

    if (experiment.holdout && variantKey === `holdout-${experiment.holdout_id}`) {
        return (
            <span className={clsx('flex items-center min-w-0', className)}>
                <div
                    className="w-2 h-2 rounded-full shrink-0"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        backgroundColor: getExperimentInsightColour(
                            getIndexForVariant(
                                legacyPrimaryMetricsResults[0],
                                variantKey,
                                getInsightType(experiment.metrics[0])
                            )
                        ),
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
                className={`ml-2 font-semibold truncate ${muted ? 'text-secondary' : ''}`}
                // eslint-disable-next-line react/forbid-dom-props
                style={fontSize ? { fontSize: `${fontSize}px` } : undefined}
            >
                {variantKey}
            </span>
        </span>
    )
}

export function ResultsTag({ metricIndex = 0 }: { metricIndex?: number }): JSX.Element {
    const { isPrimaryMetricSignificant, significanceDetails } = useValues(experimentLogic)
    const result: { color: LemonTagType; label: string } = isPrimaryMetricSignificant(metricIndex)
        ? { color: 'success', label: 'Significant' }
        : { color: 'primary', label: 'Not significant' }

    if (significanceDetails(metricIndex)) {
        return (
            <Tooltip title={significanceDetails(metricIndex)}>
                <LemonTag className="cursor-pointer" type={result.color}>
                    <b className="uppercase">{result.label}</b>
                </LemonTag>
            </Tooltip>
        )
    }

    return (
        <LemonTag type={result.color}>
            <b className="uppercase">{result.label}</b>
        </LemonTag>
    )
}

/**
 * shows a breakdown query for legacy metrics
 * @deprecated use ResultsQuery
 */
export function LegacyResultsQuery({
    result,
    showTable,
}: {
    result: ExperimentTrendsQueryResponse | ExperimentFunnelsQueryResponse | null
    showTable: boolean
}): JSX.Element {
    if (!result) {
        return <></>
    }

    const query = result.kind === NodeKind.ExperimentTrendsQuery ? result.count_query : result.funnels_query

    const fakeInsightId = Math.random().toString(36).substring(2, 15)

    return (
        <Query
            query={{
                kind: NodeKind.InsightVizNode,
                source: query,
                showTable,
                showLastComputation: true,
                showLastComputationRefresh: false,
            }}
            context={{
                insightProps: {
                    dashboardItemId: fakeInsightId as InsightShortId,
                    cachedInsight: {
                        short_id: fakeInsightId as InsightShortId,
                        query: {
                            kind: NodeKind.InsightVizNode,
                            source: query,
                        } as InsightVizNode,
                        result: result?.insight,
                        disable_baseline: true,
                    },
                    doNotLoad: true,
                },
            }}
            readOnly
        />
    )
}

/**
 * @deprecated use ExploreButton instead
 */
export function LegacyExploreButton({
    result,
    size = 'small',
}: {
    result: ExperimentTrendsQueryResponse | ExperimentFunnelsQueryResponse | null
    size?: 'xsmall' | 'small' | 'large'
}): JSX.Element {
    if (!result) {
        return <></>
    }

    const query: InsightVizNode = {
        kind: NodeKind.InsightVizNode,
        source: (result.kind === NodeKind.ExperimentTrendsQuery
            ? result.count_query
            : result.funnels_query) as InsightQueryNode,
    }

    return (
        <LemonButton
            className="ml-auto -translate-y-2"
            size={size}
            type="primary"
            icon={<IconAreaChart />}
            to={urls.insightNew({ query })}
            targetBlank
        >
            Explore as Insight
        </LemonButton>
    )
}

export function ResultsHeader(): JSX.Element {
    const { legacyPrimaryMetricsResults } = useValues(experimentLogic)

    const result = legacyPrimaryMetricsResults?.[0]

    return (
        <div className="flex">
            <div className="w-1/2">
                <div className="inline-flex items-center deprecated-space-x-2 mb-2">
                    <h2 className="m-0 font-semibold text-lg">Results</h2>
                    <ResultsTag />
                </div>
            </div>

            <div className="w-1/2 flex flex-col justify-end">
                <div className="ml-auto">
                    {/* TODO: Only show explore button if the metric is a trends or funnels query. Not supported yet with new query runner */}
                    {result &&
                        (result.kind === NodeKind.ExperimentTrendsQuery ||
                            result.kind === NodeKind.ExperimentFunnelsQuery) && <LegacyExploreButton result={result} />}
                </div>
            </div>
        </div>
    )
}

export function EllipsisAnimation(): JSX.Element {
    const [ellipsis, setEllipsis] = useState('.')

    useEffect(() => {
        let count = 1
        let direction = 1

        const interval = setInterval(() => {
            setEllipsis('.'.repeat(count))
            count += direction

            if (count === 3 || count === 1) {
                direction *= -1
            }
        }, 300)

        return () => clearInterval(interval)
    }, [])

    return <span>{ellipsis}</span>
}

export function ExperimentLoadingAnimation(): JSX.Element {
    return (
        <div className="flex flex-col flex-1 justify-center items-center">
            <LoadingBar />
            <div className="text-xs text-secondary w-44">
                <span className="mr-1">Fetching experiment results</span>
                <EllipsisAnimation />
            </div>
        </div>
    )
}

export function PageHeaderCustom(): JSX.Element {
    const {
        experimentId,
        experiment,
        isExperimentRunning,
        isExperimentStopped,
        isPrimaryMetricSignificant,
        isSingleVariantShipped,
        hasPrimaryMetricSet,
        isCreatingExperimentDashboard,
    } = useValues(experimentLogic)
    const {
        launchExperiment,
        archiveExperiment,
        createExposureCohort,
        openShipVariantModal,
        createExperimentDashboard,
        openStopExperimentModal,
    } = useActions(experimentLogic)

    const exposureCohortId = experiment?.exposure_cohort

    return (
        <PageHeader
            buttons={
                <>
                    {experiment && !isExperimentRunning && (
                        <div className="flex items-center">
                            <LemonButton
                                type="primary"
                                data-attr="launch-experiment"
                                onClick={() => launchExperiment()}
                                disabledReason={
                                    !hasPrimaryMetricSet
                                        ? 'Add at least one primary metric before launching the experiment'
                                        : undefined
                                }
                            >
                                Launch
                            </LemonButton>
                        </div>
                    )}
                    {experiment && isExperimentRunning && (
                        <div className="flex flex-row gap-2">
                            <>
                                <More
                                    overlay={
                                        <>
                                            <LemonButton
                                                to={urls.experiment(`${experiment.id}`, FORM_MODES.duplicate)}
                                                fullWidth
                                            >
                                                Duplicate
                                            </LemonButton>
                                            <LemonButton
                                                onClick={() => (exposureCohortId ? undefined : createExposureCohort())}
                                                fullWidth
                                                data-attr={`${exposureCohortId ? 'view' : 'create'}-exposure-cohort`}
                                                to={exposureCohortId ? urls.cohort(exposureCohortId) : undefined}
                                                targetBlank={!!exposureCohortId}
                                            >
                                                {exposureCohortId ? 'View' : 'Create'} exposure cohort
                                            </LemonButton>
                                            <LemonButton
                                                onClick={() => createExperimentDashboard()}
                                                fullWidth
                                                disabled={isCreatingExperimentDashboard}
                                            >
                                                Create dashboard
                                            </LemonButton>
                                        </>
                                    }
                                />
                                <LemonDivider vertical />
                            </>
                            <ResetButton experimentId={experiment.id} />
                            {!experiment.end_date && (
                                <LemonButton
                                    type="secondary"
                                    data-attr="stop-experiment"
                                    status="danger"
                                    onClick={() => openStopExperimentModal()}
                                >
                                    Stop
                                </LemonButton>
                            )}
                            {isExperimentStopped && (
                                <LemonButton
                                    type="secondary"
                                    status="danger"
                                    onClick={() => {
                                        LemonDialog.open({
                                            title: 'Archive this experiment?',
                                            content: (
                                                <div className="text-sm text-secondary">
                                                    This action will move the experiment to the archived tab. It can be
                                                    restored at any time.
                                                </div>
                                            ),
                                            primaryButton: {
                                                children: 'Archive',
                                                type: 'primary',
                                                onClick: () => archiveExperiment(),
                                                size: 'small',
                                            },
                                            secondaryButton: {
                                                children: 'Cancel',
                                                type: 'tertiary',
                                                size: 'small',
                                            },
                                        })
                                    }}
                                >
                                    <b>Archive</b>
                                </LemonButton>
                            )}
                        </div>
                    )}
                    {isPrimaryMetricSignificant(0) && !isSingleVariantShipped && (
                        <>
                            <Tooltip title="Choose a variant and roll it out to all users">
                                <LemonButton type="primary" icon={<IconFlask />} onClick={() => openShipVariantModal()}>
                                    <b>Ship a variant</b>
                                </LemonButton>
                            </Tooltip>
                            <ShipVariantModal experimentId={experimentId} />
                        </>
                    )}
                </>
            }
        />
    )
}

export function ConclusionForm({ experimentId }: { experimentId: Experiment['id'] }): JSX.Element {
    const { experiment } = useValues(experimentLogic({ experimentId }))
    const { setExperiment } = useActions(experimentLogic({ experimentId }))

    return (
        <div className="space-y-4">
            <div>
                <LemonLabel>Conclusion</LemonLabel>
                <LemonSelect
                    className="w-full"
                    dropdownMaxContentWidth={true}
                    value={experiment.conclusion}
                    options={Object.values(ExperimentConclusion).map((conclusion) => ({
                        value: conclusion,
                        label: (
                            <div className="py-2 px-1">
                                <div className="font-semibold mb-1.5">
                                    <div className="font-semibold flex items-center gap-2">
                                        <div
                                            className={clsx(
                                                'w-2 h-2 rounded-full',
                                                CONCLUSION_DISPLAY_CONFIG[conclusion].color
                                            )}
                                        />
                                        <span>{CONCLUSION_DISPLAY_CONFIG[conclusion].title}</span>
                                    </div>
                                </div>
                                <div className="text-xs text-muted">
                                    {CONCLUSION_DISPLAY_CONFIG[conclusion].description}
                                </div>
                            </div>
                        ),
                    }))}
                    onChange={(value) => {
                        setExperiment({
                            conclusion: value || undefined,
                        })
                    }}
                />
            </div>
            <div>
                <LemonLabel>Comment (optional)</LemonLabel>
                <LemonTextArea
                    className="w-full border rounded p-2"
                    minRows={6}
                    maxLength={400}
                    placeholder="Optional details about why this conclusion was selected..."
                    value={experiment.conclusion_comment || ''}
                    onChange={(value) =>
                        setExperiment({
                            conclusion_comment: value,
                        })
                    }
                />
            </div>
        </div>
    )
}

export function EditConclusionModal({ experimentId }: { experimentId: Experiment['id'] }): JSX.Element {
    const { experiment, isEditConclusionModalOpen } = useValues(experimentLogic({ experimentId }))
    const { closeEditConclusionModal, updateExperiment, restoreUnmodifiedExperiment } = useActions(
        experimentLogic({ experimentId })
    )

    return (
        <LemonModal
            isOpen={isEditConclusionModalOpen}
            onClose={closeEditConclusionModal}
            title="Edit conclusion"
            width={600}
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton
                        type="secondary"
                        onClick={() => {
                            restoreUnmodifiedExperiment()
                            closeEditConclusionModal()
                        }}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        onClick={() => {
                            updateExperiment({
                                conclusion: experiment.conclusion,
                                conclusion_comment: experiment.conclusion_comment,
                            })
                            closeEditConclusionModal()
                        }}
                        type="primary"
                        disabledReason={!experiment.conclusion && 'Select a conclusion'}
                    >
                        Save
                    </LemonButton>
                </div>
            }
        >
            <ConclusionForm experimentId={experimentId} />
        </LemonModal>
    )
}

export function StopExperimentModal({ experimentId }: { experimentId: Experiment['id'] }): JSX.Element {
    const { experiment, isStopExperimentModalOpen } = useValues(experimentLogic({ experimentId }))
    const { closeStopExperimentModal, endExperiment, restoreUnmodifiedExperiment } = useActions(
        experimentLogic({ experimentId })
    )

    return (
        <LemonModal
            isOpen={isStopExperimentModalOpen}
            onClose={() => {
                restoreUnmodifiedExperiment()
                closeStopExperimentModal()
            }}
            title="Stop experiment"
            width={600}
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton
                        type="secondary"
                        onClick={() => {
                            restoreUnmodifiedExperiment()
                            closeStopExperimentModal()
                        }}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        onClick={() => endExperiment()}
                        type="primary"
                        disabledReason={!experiment.conclusion && 'Select a conclusion'}
                    >
                        Stop experiment
                    </LemonButton>
                </div>
            }
        >
            <div>
                <div className="mb-2">
                    Stopping the experiment will end data collection. You can restart it later if needed.
                </div>
                <ConclusionForm experimentId={experimentId} />
            </div>
        </LemonModal>
    )
}

export function ShipVariantModal({ experimentId }: { experimentId: Experiment['id'] }): JSX.Element {
    const { experiment, isShipVariantModalOpen } = useValues(experimentLogic({ experimentId }))
    const { closeShipVariantModal, shipVariant } = useActions(experimentLogic({ experimentId }))
    const { aggregationLabel } = useValues(groupsModel)

    const [selectedVariantKey, setSelectedVariantKey] = useState<string | null>()
    useEffect(() => {
        if (experiment.parameters?.feature_flag_variants?.length > 1) {
            // First test variant selected by default
            setSelectedVariantKey(experiment.parameters.feature_flag_variants[1].key)
        }
    }, [experiment])

    const aggregationTargetName =
        experiment.filters.aggregation_group_type_index != null
            ? aggregationLabel(experiment.filters.aggregation_group_type_index).plural
            : 'users'

    return (
        <LemonModal
            isOpen={isShipVariantModalOpen}
            onClose={closeShipVariantModal}
            width={600}
            title="Ship a variant"
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton type="secondary" onClick={closeShipVariantModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        // TODO: revisit if it always makes sense to stop the experiment when shipping a variant
                        // does it make sense to still *monitor* the experiment after shipping the variant?
                        onClick={() => shipVariant({ selectedVariantKey, shouldStopExperiment: true })}
                        type="primary"
                    >
                        Ship variant
                    </LemonButton>
                </div>
            }
        >
            <div className="deprecated-space-y-6">
                <div className="text-sm">
                    This will roll out the selected variant to <b>100% of {aggregationTargetName}</b> and stop the
                    experiment.
                </div>
                <div className="flex items-center">
                    <div className="w-1/2 pr-4">
                        <LemonSelect
                            className="w-full"
                            data-attr="metrics-selector"
                            value={selectedVariantKey}
                            onChange={(variantKey) => {
                                setSelectedVariantKey(variantKey)
                            }}
                            options={
                                experiment.parameters?.feature_flag_variants?.map(({ key }) => ({
                                    value: key,
                                    label: (
                                        <div className="deprecated-space-x-2 inline-flex">
                                            <VariantTag experimentId={experimentId} variantKey={key} />
                                        </div>
                                    ),
                                })) || []
                            }
                        />
                    </div>
                </div>
                <LemonBanner type="info" className="mb-4">
                    For more precise control over your release, adjust the rollout percentage and release conditions in
                    the{' '}
                    <Link
                        target="_blank"
                        className="font-semibold"
                        to={experiment.feature_flag ? urls.featureFlag(experiment.feature_flag.id) : undefined}
                    >
                        {experiment.feature_flag?.key}
                    </Link>{' '}
                    feature flag.
                </LemonBanner>
            </div>
        </LemonModal>
    )
}

export const ResetButton = ({ experimentId }: { experimentId: ExperimentIdType }): JSX.Element => {
    const { experiment } = useValues(experimentLogic({ experimentId }))
    const { resetRunningExperiment } = useActions(experimentLogic)

    const onClickReset = (): void => {
        LemonDialog.open({
            title: 'Reset this experiment?',
            content: (
                <>
                    <div className="text-sm text-secondary max-w-md">
                        <p>
                            The experiment start and end dates will be reset and the experiment will go back to draft
                            mode.
                        </p>
                        <p>
                            All events collected thus far will still exist, but won't be applied to the experiment
                            unless you manually change the start date after launching the experiment again.
                        </p>
                    </div>
                    {experiment.archived && (
                        <div className="text-sm text-secondary">Resetting will also unarchive the experiment.</div>
                    )}
                </>
            ),
            primaryButton: {
                children: 'Confirm',
                type: 'primary',
                onClick: resetRunningExperiment,
                size: 'small',
            },
            secondaryButton: {
                children: 'Cancel',
                type: 'tertiary',
                size: 'small',
            },
        })
    }

    return (
        <LemonButton type="secondary" onClick={onClickReset}>
            Reset
        </LemonButton>
    )
}

export function StatusTag({ experiment }: { experiment: ExperimentType }): JSX.Element {
    const status = getExperimentStatus(experiment)
    return (
        <LemonTag type={getExperimentStatusColor(status)}>
            <b className="uppercase">{status}</b>
        </LemonTag>
    )
}

export function LoadingState(): JSX.Element {
    return (
        <div className="deprecated-space-y-4">
            <LemonSkeleton className="w-1/3 h-4" />
            <LemonSkeleton />
            <LemonSkeleton />
            <LemonSkeleton className="w-2/3 h-4" />
        </div>
    )
}

export function MetricDisplayTrends({ query }: { query: TrendsQuery | undefined }): JSX.Element {
    const event = query?.series?.[0] as unknown as ActionFilter

    if (!event) {
        return <></>
    }

    return (
        <>
            <div className="mb-2">
                <div className="flex mb-1">
                    <b>
                        <InsightLabel action={event} showCountedByTag={true} hideIcon showEventName />
                    </b>
                </div>
                <div className="deprecated-space-y-1">
                    {event.properties?.map((prop: AnyPropertyFilter) => (
                        <PropertyFilterButton key={prop.key} item={prop} />
                    ))}
                </div>
            </div>
        </>
    )
}

export function MetricDisplayFunnels({ query }: { query: FunnelsQuery }): JSX.Element {
    return (
        <>
            {(query.series || []).map((event: any, idx: number) => (
                <div key={idx} className="mb-2">
                    <div className="flex mb-1">
                        <div
                            className="shrink-0 w-6 h-6 mr-2 font-bold text-center text-primary-alt border rounded"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ backgroundColor: 'var(--bg-table)' }}
                        >
                            {idx + 1}
                        </div>
                        <b>
                            <InsightLabel action={event} hideIcon showEventName />
                        </b>
                    </div>
                    <div className="deprecated-space-y-1">
                        {event.properties?.map((prop: AnyPropertyFilter) => (
                            <PropertyFilterButton key={prop.key} item={prop} />
                        ))}
                    </div>
                </div>
            ))}
        </>
    )
}
