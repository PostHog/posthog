import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import {
    IconCopy,
    IconEye,
    IconFlask,
    IconPause,
    IconPlay,
    IconPlusSmall,
    IconRefresh,
    IconStopFilled,
} from '@posthog/icons'
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

import { useHogfetti } from 'lib/components/Hogfetti/Hogfetti'
import { InsightLabel } from 'lib/components/InsightLabel'
import { PropertyFilterButton } from 'lib/components/PropertyFilters/components/PropertyFilterButton'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { LoadingBar } from 'lib/lemon-ui/LoadingBar'
import { IconAreaChart } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { addProductIntentForCrossSell } from 'lib/utils/product-intents'
import { sceneLogic } from 'scenes/sceneLogic'
import { QuickSurveyModal } from 'scenes/surveys/QuickSurveyModal'
import { QuickSurveyType } from 'scenes/surveys/quick-create/types'
import { urls } from 'scenes/urls'

import { ScenePanel, ScenePanelActionsSection } from '~/layout/scenes/SceneLayout'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { groupsModel } from '~/models/groupsModel'
import { Query } from '~/queries/Query/Query'
import {
    ExperimentFunnelsQueryResponse,
    ExperimentTrendsQueryResponse,
    FunnelsQuery,
    InsightQueryNode,
    InsightVizNode,
    NodeKind,
    ProductIntentContext,
    ProductKey,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import {
    AccessControlLevel,
    AccessControlResourceType,
    ActionFilter,
    AnyPropertyFilter,
    ExperimentConclusion,
    ExperimentProgressStatus,
    InsightShortId,
} from '~/types'

import { DuplicateExperimentModal } from '../DuplicateExperimentModal'
import { CONCLUSION_DISPLAY_CONFIG, EXPERIMENT_VARIANT_MULTIPLE } from '../constants'
import { experimentLogic } from '../experimentLogic'
import { getExperimentStatusColor } from '../experimentsLogic'
import { modalsLogic } from '../modalsLogic'
import { getVariantColor } from '../utils'

export function VariantTag({
    variantKey,
    fontSize,
    className,
}: {
    variantKey: string
    fontSize?: number
    className?: string
}): JSX.Element {
    const { experiment, legacyPrimaryMetricsResults, usesNewQueryRunner } = useValues(experimentLogic)

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

    const variantColor = experiment.parameters?.feature_flag_variants
        ? getVariantColor(variantKey, experiment.parameters.feature_flag_variants)
        : 'var(--text-muted)'

    if (experiment.holdout && variantKey === `holdout-${experiment.holdout_id}`) {
        return (
            <span className={clsx('flex items-center min-w-0', className)}>
                <div
                    className="w-2 h-2 rounded-full shrink-0"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        backgroundColor: variantColor,
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
            {/* Only show color if using new query runner - legacy experiments are using the old funnel component */}
            {usesNewQueryRunner && (
                <div
                    className="w-2 h-2 rounded-full shrink-0"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ backgroundColor: variantColor }}
                />
            )}
            <span
                className="ml-2 text-xs font-semibold truncate text-secondary"
                // eslint-disable-next-line react/forbid-dom-props
                style={fontSize ? { fontSize: `${fontSize}px` } : undefined}
            >
                {variantKey}
            </span>
        </span>
    )
}

export function ResultsTag({ metricUuid }: { metricUuid?: string }): JSX.Element {
    const { isPrimaryMetricSignificant, significanceDetails, experiment } = useValues(experimentLogic)

    // Use first primary metric UUID if not provided
    const uuid = metricUuid || experiment.metrics?.[0]?.uuid || ''
    if (!uuid) {
        return (
            <LemonTag type="primary">
                <b className="uppercase">Not significant</b>
            </LemonTag>
        )
    }

    const result: { color: LemonTagType; label: string } = isPrimaryMetricSignificant(uuid)
        ? { color: 'success', label: 'Significant' }
        : { color: 'primary', label: 'Not significant' }

    if (significanceDetails(uuid)) {
        return (
            <Tooltip title={significanceDetails(uuid)}>
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
    const { isVisible: isPageVisible } = usePageVisibility()

    useEffect(() => {
        if (!isPageVisible) {
            return
        }

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
    }, [isPageVisible])

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
        experiment,
        isExperimentDraft,
        isExperimentRunning,
        isExperimentStopped,
        isSingleVariantShipped,
        hasPrimaryMetricSet,
        isCreatingExperimentDashboard,
        primaryMetricsResults,
        legacyPrimaryMetricsResults,
        hasMinimumExposureForResults,
        experimentLoading,
    } = useValues(experimentLogic)
    const {
        launchExperiment,
        archiveExperiment,
        createExposureCohort,
        createExperimentDashboard,
        updateExperiment,
        setHogfettiTrigger,
    } = useActions(experimentLogic)
    const { openShipVariantModal, openStopExperimentModal, openPauseExperimentModal, openResumeExperimentModal } =
        useActions(modalsLogic)
    const [duplicateModalOpen, setDuplicateModalOpen] = useState(false)
    const [surveyModalOpen, setSurveyModalOpen] = useState(false)
    const { newTab } = useActions(sceneLogic)
    const { trigger, HogfettiComponent } = useHogfetti()

    useOnMountEffect(() => {
        setHogfettiTrigger(trigger)
    })

    const exposureCohortId = experiment?.exposure_cohort

    const shouldShowShipVariantButton =
        !isExperimentDraft &&
        !isSingleVariantShipped &&
        hasMinimumExposureForResults &&
        (legacyPrimaryMetricsResults.length > 0 || primaryMetricsResults.length > 0)

    return (
        <>
            <SceneTitleSection
                name={experiment?.name}
                description={null}
                resourceType={{
                    type: 'experiment',
                }}
                isLoading={experimentLoading}
                onNameChange={(name) => updateExperiment({ name })}
                onDescriptionChange={(description) => updateExperiment({ description })}
                canEdit={userHasAccess(
                    AccessControlResourceType.Experiment,
                    AccessControlLevel.Editor,
                    experiment.user_access_level
                )}
                renameDebounceMs={0}
                saveOnBlur
                actions={
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
                                    size="small"
                                >
                                    Launch
                                </LemonButton>
                            </div>
                        )}
                        {experiment && isExperimentRunning && (
                            <div className="flex flex-row gap-2">
                                {isExperimentStopped && (
                                    <LemonButton
                                        type="secondary"
                                        status="danger"
                                        onClick={() => {
                                            LemonDialog.open({
                                                title: 'Archive this experiment?',
                                                content: (
                                                    <div className="text-sm text-secondary">
                                                        This action will move the experiment to the archived tab. It can
                                                        be restored at any time.
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
                                        size="small"
                                    >
                                        <b>Archive</b>
                                    </LemonButton>
                                )}
                            </div>
                        )}
                        {shouldShowShipVariantButton && (
                            <>
                                <Tooltip title="Choose a variant and roll it out to all users">
                                    <LemonButton
                                        type="primary"
                                        icon={<IconFlask />}
                                        onClick={() => openShipVariantModal()}
                                        size="small"
                                    >
                                        <b>Ship a variant</b>
                                    </LemonButton>
                                </Tooltip>
                                <ShipVariantModal />
                            </>
                        )}
                        {experiment && (
                            <DuplicateExperimentModal
                                isOpen={duplicateModalOpen}
                                onClose={() => setDuplicateModalOpen(false)}
                                experiment={experiment}
                            />
                        )}
                    </>
                }
            />
            <HogfettiComponent />

            {experiment && isExperimentRunning && (
                <ScenePanel>
                    <ScenePanelActionsSection>
                        <ButtonPrimitive menuItem onClick={() => setDuplicateModalOpen(true)}>
                            <IconCopy />
                            Duplicate
                        </ButtonPrimitive>

                        {exposureCohortId ? (
                            // TODO: add custom back button to the destination page
                            <Link
                                to={urls.cohort(exposureCohortId)}
                                buttonProps={{
                                    menuItem: true,
                                }}
                                data-attr="view-exposure-cohort"
                                onClick={() => newTab(urls.cohort(exposureCohortId))}
                            >
                                <IconEye /> View exposure cohort as new tab
                            </Link>
                        ) : (
                            <ButtonPrimitive
                                menuItem
                                onClick={() => createExposureCohort()}
                                data-attr="create-exposure-cohort"
                            >
                                <IconPlusSmall /> Create exposure cohort
                            </ButtonPrimitive>
                        )}
                        <ButtonPrimitive
                            menuItem
                            onClick={() => createExperimentDashboard()}
                            disabledReasons={{
                                'Creating dashboard...': isCreatingExperimentDashboard,
                            }}
                        >
                            <IconPlusSmall /> Create dashboard
                        </ButtonPrimitive>

                        {experiment.feature_flag && (
                            <ButtonPrimitive
                                menuItem
                                onClick={() => {
                                    setSurveyModalOpen(true)
                                    void addProductIntentForCrossSell({
                                        from: ProductKey.EXPERIMENTS,
                                        to: ProductKey.SURVEYS,
                                        intent_context: ProductIntentContext.QUICK_SURVEY_STARTED,
                                    })
                                }}
                            >
                                <IconPlusSmall /> Create survey
                            </ButtonPrimitive>
                        )}

                        <LemonDivider />

                        <ResetButton />

                        {!experiment.end_date &&
                            experiment.feature_flag &&
                            (experiment.feature_flag.active ? (
                                <ButtonPrimitive
                                    variant="danger"
                                    menuItem
                                    data-attr="pause-experiment"
                                    onClick={() => openPauseExperimentModal()}
                                >
                                    <IconPause /> Pause experiment
                                </ButtonPrimitive>
                            ) : (
                                <ButtonPrimitive
                                    menuItem
                                    data-attr="resume-experiment"
                                    onClick={() => openResumeExperimentModal()}
                                >
                                    <IconPlay /> Resume experiment
                                </ButtonPrimitive>
                            ))}

                        {!experiment.end_date && (
                            <ButtonPrimitive
                                variant="danger"
                                menuItem
                                data-attr="stop-experiment"
                                onClick={() => openStopExperimentModal()}
                            >
                                <IconStopFilled /> Stop
                            </ButtonPrimitive>
                        )}
                        <PauseExperimentModal />
                        <ResumeExperimentModal />
                    </ScenePanelActionsSection>
                </ScenePanel>
            )}
            <QuickSurveyModal
                context={{ type: QuickSurveyType.EXPERIMENT, experiment }}
                isOpen={surveyModalOpen}
                onCancel={() => setSurveyModalOpen(false)}
            />
        </>
    )
}

export function ConclusionForm(): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { setExperiment } = useActions(experimentLogic)

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

export function EditConclusionModal(): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { updateExperiment, restoreUnmodifiedExperiment } = useActions(experimentLogic)
    const { closeEditConclusionModal } = useActions(modalsLogic)
    const { isEditConclusionModalOpen } = useValues(modalsLogic)

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
            <ConclusionForm />
        </LemonModal>
    )
}

export function StopExperimentModal(): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { endExperiment, restoreUnmodifiedExperiment } = useActions(experimentLogic)
    const { closeStopExperimentModal } = useActions(modalsLogic)
    const { isStopExperimentModalOpen } = useValues(modalsLogic)

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
            <div className="space-y-4">
                <div>
                    Stopping the experiment will mark when to stop counting events in the results. Your feature flag
                    will continue working normally and events will still be tracked. You can restart the experiment
                    later if needed.
                </div>
                <div>
                    To roll out a specific variant to all users instead, use the 'Ship a variant' button or adjust the
                    feature flag settings.
                </div>
                <ConclusionForm />
            </div>
        </LemonModal>
    )
}

export function PauseExperimentModal(): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { pauseExperiment } = useActions(experimentLogic)
    const { closePauseExperimentModal } = useActions(modalsLogic)
    const { isPauseExperimentModalOpen } = useValues(modalsLogic)

    return (
        <LemonModal
            isOpen={isPauseExperimentModalOpen}
            onClose={closePauseExperimentModal}
            title="Pause experiment"
            width={600}
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton type="secondary" onClick={closePauseExperimentModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        onClick={() => pauseExperiment()}
                        type="primary"
                        status="danger"
                        disabledReason={!experiment.feature_flag && 'No feature flag linked'}
                    >
                        Pause experiment
                    </LemonButton>
                </div>
            }
        >
            <div className="space-y-4">
                <div>
                    Pausing the experiment will <b>disable the feature flag</b>, preventing any users from seeing the
                    experiment variants. This is useful when you need to quickly stop exposing users to the experiment.
                </div>
                <div>The experiment can be resumed at any time. All collected data will be preserved.</div>
            </div>
        </LemonModal>
    )
}

export function ResumeExperimentModal(): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { resumeExperiment } = useActions(experimentLogic)
    const { closeResumeExperimentModal } = useActions(modalsLogic)
    const { isResumeExperimentModalOpen } = useValues(modalsLogic)

    return (
        <LemonModal
            isOpen={isResumeExperimentModalOpen}
            onClose={closeResumeExperimentModal}
            title="Resume experiment"
            width={600}
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton type="secondary" onClick={closeResumeExperimentModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        onClick={() => resumeExperiment()}
                        type="primary"
                        disabledReason={!experiment.feature_flag && 'No feature flag linked'}
                    >
                        Resume experiment
                    </LemonButton>
                </div>
            }
        >
            <div className="space-y-4">
                <div>
                    Resuming the experiment will <b>enable the feature flag</b>, allowing users to see the experiment
                    variants again. This will continue the experiment from where it was paused.
                </div>
                <div>All previously collected data is preserved and new events will be tracked.</div>
            </div>
        </LemonModal>
    )
}

export function ShipVariantModal(): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { shipVariant, restoreUnmodifiedExperiment } = useActions(experimentLogic)
    const { closeShipVariantModal } = useActions(modalsLogic)
    const { isShipVariantModalOpen } = useValues(modalsLogic)
    const { aggregationLabel } = useValues(groupsModel)

    const [selectedVariantKey, setSelectedVariantKey] = useState<string | null>()

    useEffect(() => {
        if (experiment.parameters?.feature_flag_variants?.length > 1) {
            // First test variant selected by default
            setSelectedVariantKey(experiment.parameters.feature_flag_variants[1].key)
        }
    }, [
        experiment.id,
        experiment.parameters?.feature_flag_variants?.length,
        experiment.parameters?.feature_flag_variants,
    ])

    const aggregationTargetName =
        experiment.filters.aggregation_group_type_index != null
            ? aggregationLabel(experiment.filters.aggregation_group_type_index).plural
            : 'users'

    return (
        <>
            <LemonModal
                isOpen={isShipVariantModalOpen}
                onClose={() => {
                    restoreUnmodifiedExperiment()
                    closeShipVariantModal()
                }}
                width={600}
                title="Ship a variant"
                footer={
                    <div className="flex items-center gap-2">
                        <LemonButton
                            type="secondary"
                            onClick={() => {
                                restoreUnmodifiedExperiment()
                                closeShipVariantModal()
                            }}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            onClick={() => {
                                shipVariant({ selectedVariantKey, shouldStopExperiment: true })
                            }}
                            type="primary"
                            disabledReason={!experiment.conclusion && 'Select a conclusion'}
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
                                                <VariantTag variantKey={key} />
                                            </div>
                                        ),
                                    })) || []
                                }
                            />
                        </div>
                    </div>
                    <ConclusionForm />
                    <LemonBanner type="info" className="mb-4">
                        For more precise control over your release, adjust the rollout percentage and release conditions
                        in the{' '}
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
        </>
    )
}

export const ResetButton = (): JSX.Element => {
    const { experiment } = useValues(experimentLogic)
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
        <ButtonPrimitive variant="danger" menuItem onClick={onClickReset} data-attr="reset-experiment">
            <IconRefresh /> Reset experiment
        </ButtonPrimitive>
    )
}

export function StatusTag({ status }: { status: ExperimentProgressStatus }): JSX.Element {
    return (
        <LemonTag type={getExperimentStatusColor(status)} className="cursor-default">
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
                            style={{ backgroundColor: 'var(--color-bg-table)' }}
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
