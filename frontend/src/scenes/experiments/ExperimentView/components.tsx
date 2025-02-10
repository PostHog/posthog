import { IconFlask } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonDivider,
    LemonModal,
    LemonSelect,
    LemonSkeleton,
    LemonTag,
    LemonTagType,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { AnimationType } from 'lib/animations/animations'
import { Animation } from 'lib/components/Animation/Animation'
import { InsightLabel } from 'lib/components/InsightLabel'
import { PageHeader } from 'lib/components/PageHeader'
import { PropertyFilterButton } from 'lib/components/PropertyFilters/components/PropertyFilterButton'
import { IconAreaChart } from 'lib/lemon-ui/icons'
import { More } from 'lib/lemon-ui/LemonButton/More'
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
    ExperimentIdType,
    InsightShortId,
} from '~/types'

import { experimentLogic } from '../experimentLogic'
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
    const { experiment, getIndexForVariant, metricResults } = useValues(experimentLogic({ experimentId }))

    if (!metricResults) {
        return <></>
    }

    if (experiment.holdout && variantKey === `holdout-${experiment.holdout_id}`) {
        return (
            <span className={clsx('flex items-center min-w-0', className)}>
                <div
                    className="w-2 h-2 rounded-full shrink-0"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        backgroundColor: getExperimentInsightColour(getIndexForVariant(metricResults[0], variantKey)),
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
            <div
                className="w-2 h-2 rounded-full shrink-0"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    backgroundColor: getExperimentInsightColour(getIndexForVariant(metricResults[0], variantKey)),
                }}
            />
            <span
                className={`ml-2 font-semibold truncate ${muted ? 'text-[var(--text-tertiary)]' : ''}`}
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

export function ResultsQuery({
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

export function ExploreButton({
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
    const { metricResults } = useValues(experimentLogic)

    const result = metricResults?.[0]

    return (
        <div className="flex">
            <div className="w-1/2">
                <div className="inline-flex items-center space-x-2 mb-2">
                    <h2 className="m-0 font-semibold text-lg">Results</h2>
                    <ResultsTag />
                </div>
            </div>

            <div className="w-1/2 flex flex-col justify-end">
                <div className="ml-auto">{result && <ExploreButton result={result} />}</div>
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
            <Animation type={AnimationType.LaptopHog} />
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
        endExperiment,
        archiveExperiment,
        createExposureCohort,
        openShipVariantModal,
        createExperimentDashboard,
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
                                    onClick={() => {
                                        LemonDialog.open({
                                            title: 'Stop this experiment?',
                                            content: (
                                                <div className="text-sm text-secondary">
                                                    This action will end data collection. The experiment can be
                                                    restarted later if needed.
                                                </div>
                                            ),
                                            primaryButton: {
                                                children: 'Stop',
                                                type: 'primary',
                                                onClick: () => endExperiment(),
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
            <div className="space-y-6">
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
                                        <div className="space-x-2 inline-flex">
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
                    <div className="text-sm text-secondary">
                        All data collected so far will be discarded and the experiment will go back to draft mode.
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
        <div className="space-y-4">
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
                <div className="space-y-1">
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
