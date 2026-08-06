import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useState } from 'react'

import * as experimentPng from '@posthog/brand/hoggies/png/experiment'
import { LemonInput, LemonSelect, LemonTag, Tooltip, lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { pngHoggie } from 'lib/brand/hoggies'
import { AccessControlAction } from 'lib/components/AccessControlAction'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { BulkUpdateTagsButton } from 'lib/components/BulkActions/BulkUpdateTagsButton'
import { MemberMultiSelect } from 'lib/components/MemberMultiSelect'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { TagSelect } from 'lib/components/TagSelect'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { atColumn, createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { accessLevelSatisfied } from 'lib/utils/accessControlUtils'
import { addProductIntentForCrossSell } from 'lib/utils/product-intents'
import { pluralize } from 'lib/utils/strings'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { toParams } from 'lib/utils/url'
import MaxTool from 'scenes/max/MaxTool'
import { useMaxTool } from 'scenes/max/useMaxTool'
import { organizationLogic } from 'scenes/organizationLogic'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { QuickSurveyType } from 'scenes/surveys/quick-create/types'
import { QuickSurveyModal } from 'scenes/surveys/QuickSurveyModal'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import {
    AccessControlLevel,
    AccessControlResourceType,
    ActivityScope,
    Experiment,
    ExperimentConclusion,
    ExperimentStatus,
    ExperimentsTabs,
} from '~/types'

import { CONCLUSION_DISPLAY_CONFIG } from './constants'
import { CopyExperimentToProjectModal } from './CopyExperimentToProjectModal'
import { DuplicateExperimentModal } from './DuplicateExperimentModal'
import { canArchiveExperiment, confirmArchiveExperiment, confirmDeleteExperiment } from './experimentActions'
import {
    EXPERIMENTS_PER_PAGE,
    ExperimentsFilters,
    experimentsLogic,
    getExperimentStatus,
    getShippedVariantKey,
    isSingleVariantShipped,
} from './experimentsLogic'
import { ExperimentsSettings } from './ExperimentsSettings'
import { ExperimentVelocityStats } from './ExperimentVelocityStats'
import { StatusTag } from './ExperimentView/StatusTag'
import { Holdouts } from './Holdouts'
import { SharedMetrics } from './SharedMetrics/SharedMetrics'

const HedgehogExperiment = pngHoggie(experimentPng)

export const scene: SceneExport = {
    component: Experiments,
    logic: experimentsLogic,
    productKey: ProductKey.EXPERIMENTS,
}

export const EXPERIMENTS_PRODUCT_DESCRIPTION =
    'Experiments help you test changes to your product to see which changes will lead to optimal results. Automatic statistical calculations let you see if the results are valid or due to chance.'

// Component for the survey button using QuickSurveyModal
const ExperimentSurveyButton = ({
    experiment,
    onOpenModal,
}: {
    experiment: Experiment
    onOpenModal: () => void
}): JSX.Element => {
    // Don't show the button if there's no feature flag associated with the experiment
    if (!experiment.feature_flag) {
        return <></>
    }

    return (
        <LemonButton onClick={onOpenModal} size="small" fullWidth data-attr="create-survey">
            Create survey
        </LemonButton>
    )
}

const getExperimentDuration = (experiment: Experiment): number | undefined => {
    return experiment.end_date
        ? dayjs(experiment.end_date).diff(dayjs(experiment.start_date), 'day')
        : experiment.start_date
          ? dayjs().diff(dayjs(experiment.start_date), 'day')
          : undefined
}

const ExperimentsTableFilters = ({
    filters,
    onFiltersChange,
}: {
    filters: ExperimentsFilters
    onFiltersChange: (filters: ExperimentsFilters, replace?: boolean) => void
}): JSX.Element => {
    return (
        <div className="flex justify-between gap-2 flex-wrap">
            <div className="flex items-center gap-6">
                <Shortcut
                    name="SearchExperiments"
                    keybind={[keyBinds.filter]}
                    intent="Search experiments"
                    interaction="click"
                    scope={Scene.Experiments}
                >
                    <LemonInput
                        type="search"
                        placeholder="Search experiments"
                        onChange={(search) => onFiltersChange({ search, page: 1 })}
                        value={filters.search || ''}
                    />
                </Shortcut>
                <div className="flex items-center gap-2">
                    <span>
                        <b>Status</b>
                    </span>
                    <LemonSelect
                        size="xsmall"
                        onChange={(status) => {
                            if (status === 'all') {
                                const { status: _, ...restFilters } = filters
                                onFiltersChange({ ...restFilters, page: 1 }, true)
                            } else {
                                onFiltersChange({ status: status as ExperimentStatus, page: 1 })
                            }
                        }}
                        options={
                            [
                                { label: 'All', value: 'all' },
                                { label: 'Draft', value: ExperimentStatus.Draft },
                                { label: 'Running', value: ExperimentStatus.Running },
                                { label: 'Paused', value: ExperimentStatus.Paused },
                                { label: 'Exposure frozen', value: ExperimentStatus.ExposureFrozen },
                                { label: 'Complete', value: ExperimentStatus.Stopped },
                            ] as { label: string; value: string }[]
                        }
                        value={filters.status ?? 'all'}
                        dropdownMatchSelectWidth={false}
                        dropdownMaxContentWidth
                    />
                    <span className="ml-1">
                        <b>Created by</b>
                    </span>
                    <MemberMultiSelect
                        defaultLabel="Any user"
                        value={filters.created_by_id ?? []}
                        size="xsmall"
                        onChange={(userIds) => {
                            if (!userIds.length) {
                                const { created_by_id, ...restFilters } = filters
                                onFiltersChange({ ...restFilters, page: 1 }, true)
                            } else {
                                onFiltersChange({ created_by_id: userIds, page: 1 })
                            }
                        }}
                    />
                    <span className="ml-1">
                        <b>Tags</b>
                    </span>
                    <TagSelect
                        defaultLabel="Any tags"
                        value={filters.tags || []}
                        onChange={(tags) => {
                            onFiltersChange({ tags: tags.length > 0 ? tags : undefined, page: 1 })
                        }}
                        data-attr="experiment-select-tags"
                    />
                    <span className="ml-1">
                        <b>Exclude tags</b>
                    </span>
                    <TagSelect
                        defaultLabel="No tags"
                        value={filters.excluded_tags || []}
                        onChange={(excludedTags) => {
                            onFiltersChange({
                                excluded_tags: excludedTags.length > 0 ? excludedTags : undefined,
                                page: 1,
                            })
                        }}
                        data-attr="experiment-select-excluded-tags"
                    />
                    <span className="ml-1">
                        <b>Archived</b>
                    </span>
                    <LemonSelect
                        size="xsmall"
                        onChange={(value) => {
                            onFiltersChange({ archived: value === 'archived', page: 1 })
                        }}
                        options={[
                            { label: 'Active', value: 'active' },
                            { label: 'Archived', value: 'archived' },
                        ]}
                        value={filters.archived ? 'archived' : 'active'}
                        dropdownMatchSelectWidth={false}
                        dropdownMaxContentWidth
                    />
                </div>
            </div>
            <ExperimentVelocityStats />
        </div>
    )
}

const ExperimentsTable = ({
    openDuplicateModal,
    openSurveyModal,
    openCopyToProjectModal,
}: {
    openDuplicateModal: (experiment: Experiment) => void
    openSurveyModal: (experiment: Experiment) => void
    openCopyToProjectModal: (experiment: Experiment) => void
}): JSX.Element => {
    const {
        currentProjectId,
        experiments,
        experimentsLoading,
        tab,
        shouldShowEmptyState,
        filters,
        count,
        pagination,
        paramsFromFilters,
    } = useValues(experimentsLogic)
    const { loadExperiments, archiveExperiment, unarchiveExperiment, setExperimentsFilters } =
        useActions(experimentsLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const hasMultipleProjects = (currentOrganization?.projects?.length ?? 0) > 1

    const [matchingExperimentIds, setMatchingExperimentIds] = useState<readonly number[] | null>(null)
    const [matchingExperimentIdsLoading, setMatchingExperimentIdsLoading] = useState(false)
    // State rather than a ref so mounting the slot re-renders and the bar's portal finds it.
    const [bulkSelectionBarContainer, setBulkSelectionBarContainer] = useState<HTMLDivElement | null>(null)

    // Changing a filter changes which experiments the bulk bar refers to, so drop the selection and
    // any cached "all matching" IDs. Page is excluded: selections deliberately span pages.
    const { page: _page, ...filtersWithoutPage } = filters
    const filterIdentity = JSON.stringify(filtersWithoutPage)
    useEffect(() => {
        setMatchingExperimentIds(null)
    }, [filterIdentity])

    const page = filters.page || 1
    const startCount = count === 0 ? 0 : (page - 1) * EXPERIMENTS_PER_PAGE + 1
    const endCount = page * EXPERIMENTS_PER_PAGE < count ? page * EXPERIMENTS_PER_PAGE : count

    const columns: LemonTableColumns<Experiment> = [
        {
            title: 'Name',
            dataIndex: 'name',
            className: 'ph-no-capture',
            sticky: true,
            width: '40%',
            render: function Render(_, experiment: Experiment) {
                return (
                    <LemonTableLink
                        to={experiment.id ? urls.experiment(experiment.id) : undefined}
                        title={
                            <>
                                {stringWithWBR(experiment.name, 17)}
                                {experiment.type === 'web' && (
                                    <LemonTag type="default" className="ml-1">
                                        No-code
                                    </LemonTag>
                                )}
                                {experiment.is_legacy && (
                                    <Tooltip
                                        title="This experiment uses the legacy engine, so some features and improvements may be missing."
                                        docLink="https://posthog.com/docs/experiments/new-experimentation-engine"
                                    >
                                        <LemonTag type="warning" className="ml-1">
                                            Legacy
                                        </LemonTag>
                                    </Tooltip>
                                )}
                                {isSingleVariantShipped(experiment) && (
                                    <Tooltip
                                        title={`Variant "${getShippedVariantKey(experiment)}" has been rolled out to 100% of users`}
                                    >
                                        <LemonTag type="completion" className="ml-1">
                                            <b className="uppercase">100% rollout</b>
                                        </LemonTag>
                                    </Tooltip>
                                )}
                            </>
                        }
                        description={
                            experiment.description ? (
                                // Hypotheses can run many paragraphs, so clamp to keep list rows compact
                                <LemonMarkdown className="max-w-[30rem] line-clamp-2" lowKeyHeadings disableImages>
                                    {experiment.description}
                                </LemonMarkdown>
                            ) : undefined
                        }
                    />
                )
            },
        },
        {
            title: 'Tags',
            dataIndex: 'tags' as keyof Experiment,
            render: function Render(_, experiment: Experiment) {
                const tags = experiment.tags
                if (!tags || tags.length === 0) {
                    return null
                }
                return <ObjectTags tags={tags} staticOnly />
            },
        } as LemonTableColumn<Experiment, keyof Experiment | undefined>,
        createdByColumn<Experiment>() as LemonTableColumn<Experiment, keyof Experiment | undefined>,
        createdAtColumn<Experiment>() as LemonTableColumn<Experiment, keyof Experiment | undefined>,
        atColumn('start_date', 'Started') as LemonTableColumn<Experiment, keyof Experiment | undefined>,
        {
            title: 'Duration',
            key: 'duration',
            render: function Render(_, experiment: Experiment) {
                const duration = getExperimentDuration(experiment)

                return <div>{duration !== undefined ? `${duration} day${duration !== 1 ? 's' : ''}` : '—'}</div>
            },
            sorter: (a, b) => {
                const durationA = getExperimentDuration(a) ?? -1
                const durationB = getExperimentDuration(b) ?? -1
                return durationA > durationB ? 1 : -1
            },
            align: 'right',
        },
        {
            title: 'Remaining',
            key: 'remaining_time',
            width: 80,
            render: function Render(_, experiment: Experiment) {
                const remainingDays = experiment.running_time_calculation?.recommended_running_time
                const daysElapsed = experiment.start_date
                    ? dayjs().diff(dayjs(experiment.start_date), 'day')
                    : undefined

                if (remainingDays === undefined || remainingDays === null) {
                    return (
                        <Tooltip title="Remaining time will be calculated once the experiment has enough data">
                            <div className="w-full">
                                <LemonProgress percent={0} bgColor="var(--border)" strokeColor="var(--border)" />
                            </div>
                        </Tooltip>
                    )
                }

                if (remainingDays === 0) {
                    return (
                        <Tooltip title="Recommended sample size reached">
                            <div className="w-full">
                                <LemonProgress percent={100} strokeColor="var(--success)" />
                            </div>
                        </Tooltip>
                    )
                }

                const totalEstimatedDays = (daysElapsed ?? 0) + remainingDays
                const progress = totalEstimatedDays > 0 ? ((daysElapsed ?? 0) / totalEstimatedDays) * 100 : 0

                return (
                    <Tooltip
                        title={`~${Math.ceil(remainingDays)} day${Math.ceil(remainingDays) !== 1 ? 's' : ''} remaining`}
                    >
                        <div className="w-full">
                            <LemonProgress percent={progress} />
                        </div>
                    </Tooltip>
                )
            },
        },
        {
            title: 'Status',
            key: 'status',
            render: function Render(_, experiment: Experiment) {
                return <StatusTag status={getExperimentStatus(experiment)} />
            },
            align: 'center',
            sorter: (a, b) => {
                const statusA = getExperimentStatus(a)
                const statusB = getExperimentStatus(b)

                const score: Record<ExperimentStatus, number> = {
                    [ExperimentStatus.Draft]: 1,
                    [ExperimentStatus.Running]: 2,
                    [ExperimentStatus.Paused]: 3,
                    [ExperimentStatus.ExposureFrozen]: 4,
                    [ExperimentStatus.Stopped]: 5,
                }
                return score[statusA] > score[statusB] ? 1 : -1
            },
        },
        {
            title: 'Result',
            key: 'conclusion',
            render: function Render(_, experiment: Experiment) {
                if (!experiment.conclusion) {
                    return <span className="text-secondary">—</span>
                }
                const config = CONCLUSION_DISPLAY_CONFIG[experiment.conclusion]
                const tooltip = experiment.conclusion_comment
                    ? `${config.description} — ${experiment.conclusion_comment}`
                    : config.description
                return (
                    <Tooltip title={tooltip}>
                        <div className="flex items-center gap-2 cursor-default">
                            <div className={clsx('w-2 h-2 rounded-full', config.color)} />
                            <span className="font-medium">{config.title}</span>
                        </div>
                    </Tooltip>
                )
            },
            align: 'left',
            sorter: (a, b) => {
                const conclusionScore: Record<ExperimentConclusion, number> = {
                    [ExperimentConclusion.Won]: 1,
                    [ExperimentConclusion.Lost]: 2,
                    [ExperimentConclusion.Inconclusive]: 3,
                    [ExperimentConclusion.StoppedEarly]: 4,
                    [ExperimentConclusion.Invalid]: 5,
                }
                const aScore = a.conclusion ? conclusionScore[a.conclusion] : 6
                const bScore = b.conclusion ? conclusionScore[b.conclusion] : 6
                return aScore - bScore
            },
        },
        {
            width: 0,
            render: function Render(_, experiment: Experiment) {
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton to={urls.experiment(`${experiment.id}`)} size="small" fullWidth>
                                    View
                                </LemonButton>
                                <LemonButton
                                    onClick={() => openDuplicateModal(experiment)}
                                    size="small"
                                    fullWidth
                                    disabledReason={
                                        experiment.is_legacy
                                            ? 'Not supported for experiments using legacy metrics. Please recreate the experiment manually.'
                                            : undefined
                                    }
                                >
                                    Duplicate
                                </LemonButton>
                                {hasMultipleProjects && (
                                    <LemonButton
                                        onClick={() => openCopyToProjectModal(experiment)}
                                        size="small"
                                        fullWidth
                                        disabledReason={
                                            experiment.is_legacy
                                                ? 'Copying is not supported for experiments using legacy metrics.'
                                                : undefined
                                        }
                                    >
                                        Copy to project
                                    </LemonButton>
                                )}
                                <ExperimentSurveyButton
                                    experiment={experiment}
                                    onOpenModal={() => {
                                        openSurveyModal(experiment)
                                        void addProductIntentForCrossSell({
                                            from: ProductKey.EXPERIMENTS,
                                            to: ProductKey.SURVEYS,
                                            intent_context: ProductIntentContext.QUICK_SURVEY_STARTED,
                                        })
                                    }}
                                />
                                {canArchiveExperiment(experiment) && (
                                    <AccessControlAction
                                        resourceType={AccessControlResourceType.Experiment}
                                        minAccessLevel={AccessControlLevel.Editor}
                                        userAccessLevel={experiment.user_access_level}
                                    >
                                        <LemonButton
                                            onClick={() =>
                                                confirmArchiveExperiment(experiment, (disableFlag) =>
                                                    archiveExperiment({
                                                        id: experiment.id as number,
                                                        disableFeatureFlag: disableFlag,
                                                    })
                                                )
                                            }
                                            data-attr={`experiment-${experiment.id}-dropdown-archive`}
                                            fullWidth
                                        >
                                            Archive experiment
                                        </LemonButton>
                                    </AccessControlAction>
                                )}
                                {experiment.archived && (
                                    <AccessControlAction
                                        resourceType={AccessControlResourceType.Experiment}
                                        minAccessLevel={AccessControlLevel.Editor}
                                        userAccessLevel={experiment.user_access_level}
                                    >
                                        <LemonButton
                                            onClick={() => unarchiveExperiment(experiment.id as number)}
                                            data-attr={`experiment-${experiment.id}-dropdown-unarchive`}
                                            fullWidth
                                        >
                                            Unarchive experiment
                                        </LemonButton>
                                    </AccessControlAction>
                                )}
                                <LemonDivider />
                                <AccessControlAction
                                    resourceType={AccessControlResourceType.Experiment}
                                    minAccessLevel={AccessControlLevel.Editor}
                                    userAccessLevel={experiment.user_access_level}
                                >
                                    <LemonButton
                                        status="danger"
                                        onClick={() =>
                                            confirmDeleteExperiment({
                                                projectId: currentProjectId,
                                                experiment,
                                                onDelete: () => loadExperiments(),
                                            })
                                        }
                                        data-attr={`experiment-${experiment.id}-dropdown-remove`}
                                        fullWidth
                                    >
                                        Delete experiment
                                    </LemonButton>
                                </AccessControlAction>
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <SceneContent>
            {tab === ExperimentsTabs.All && (
                <AccessControlAction
                    resourceType={AccessControlResourceType.Experiment}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <ProductIntroduction
                        productName="Experiments"
                        productKey={ProductKey.EXPERIMENTS}
                        thingName="experiment"
                        description={EXPERIMENTS_PRODUCT_DESCRIPTION}
                        docsURL="https://posthog.com/docs/experiments"
                        action={() => router.actions.push(urls.experiment('new'))}
                        isEmpty={shouldShowEmptyState}
                        customHog={HedgehogExperiment}
                        className="my-0"
                        mcpSurfaceKey="experiments.create"
                    />
                </AccessControlAction>
            )}
            <ExperimentsTableFilters filters={filters} onFiltersChange={setExperimentsFilters} />
            <LemonDivider className="my-0" />
            {count ? (
                // min-h-9 matches the bulk selection bar's own height so the row doesn't jump
                // when a selection appears. The bar portals into the right-hand slot.
                <div className="flex items-center justify-between gap-2 min-h-9" data-attr="experiments-count-row">
                    <span className="text-secondary">
                        {`${startCount}${endCount - startCount > 1 ? '-' + endCount : ''} of ${pluralize(count, 'experiment')}`}
                    </span>
                    <div ref={setBulkSelectionBarContainer} className="flex items-center" />
                </div>
            ) : null}

            <div data-attr="experiments-table-container">
                <LemonTable
                    dataSource={experiments.results}
                    columns={columns}
                    rowKey="id"
                    loading={experimentsLoading}
                    defaultSorting={{
                        columnKey: 'created_at',
                        order: -1,
                    }}
                    noSortingCancellation
                    pagination={pagination}
                    nouns={['experiment', 'experiments']}
                    data-attr="experiment-table"
                    emptyState="No results for this filter, change filter or create a new experiment."
                    onSort={(newSorting) =>
                        setExperimentsFilters({
                            order: newSorting
                                ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}`
                                : undefined,
                            page: 1,
                        })
                    }
                    bulkSelection={{
                        barPortalTarget: bulkSelectionBarContainer,
                        clearSelectionKey: filterIdentity,
                        getKey: (experiment: Experiment): number =>
                            typeof experiment.id === 'number' ? experiment.id : -1,
                        isRowSelectable: (experiment: Experiment) =>
                            typeof experiment.id !== 'number'
                                ? false
                                : !experiment.user_access_level ||
                                    accessLevelSatisfied(
                                        AccessControlResourceType.Experiment,
                                        experiment.user_access_level,
                                        AccessControlLevel.Editor
                                    )
                                  ? true
                                  : { disabledReason: "You don't have permission to edit this experiment." },
                        rowAriaLabel: (experiment: Experiment) => `Select experiment ${experiment.name}`,
                        headerAriaLabel: 'Select all experiments on this page',
                        noun: ['experiment', 'experiments'],
                        renderActions: (ctx) => {
                            const selectedKeysSet = new Set(ctx.selectedKeys)
                            const isAllMatchingSelected =
                                matchingExperimentIds !== null &&
                                ctx.selectedCount === matchingExperimentIds.length &&
                                matchingExperimentIds.every((id) => selectedKeysSet.has(id))
                            const showSelectAllMatchingBanner =
                                !isAllMatchingSelected &&
                                ctx.selectedCount >= EXPERIMENTS_PER_PAGE &&
                                count > ctx.selectedCount
                            return (
                                <>
                                    {isAllMatchingSelected && (
                                        <span className="text-muted text-sm">
                                            All {ctx.selectedCount} matching experiments selected
                                        </span>
                                    )}
                                    {showSelectAllMatchingBanner && (
                                        <LemonButton
                                            type="secondary"
                                            size="small"
                                            loading={matchingExperimentIdsLoading}
                                            onClick={async () => {
                                                setMatchingExperimentIdsLoading(true)
                                                try {
                                                    const { limit, offset, ...restFilters } = paramsFromFilters
                                                    const response = (await api.get(
                                                        `api/projects/${currentProjectId}/experiments/matching_ids/?${toParams(restFilters)}`
                                                    )) as { ids: number[]; total: number }
                                                    setMatchingExperimentIds(response.ids)
                                                    ctx.setSelectedKeys(response.ids)
                                                } catch {
                                                    lemonToast.error(
                                                        "Couldn't select all matching experiments. Please try again."
                                                    )
                                                } finally {
                                                    setMatchingExperimentIdsLoading(false)
                                                }
                                            }}
                                        >
                                            Select all {count} matching experiments
                                        </LemonButton>
                                    )}
                                    <BulkUpdateTagsButton
                                        resource="experiments"
                                        selectedIds={ctx.selectedKeys}
                                        onSuccess={() => {
                                            ctx.clearSelection()
                                            setMatchingExperimentIds(null)
                                            loadExperiments()
                                        }}
                                    />
                                </>
                            )
                        },
                    }}
                />
            </div>
        </SceneContent>
    )
}

export function Experiments(): JSX.Element {
    const { tab } = useValues(experimentsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { setExperimentsTab, loadExperiments } = useActions(experimentsLogic)
    const [duplicateModalExperiment, setDuplicateModalExperiment] = useState<Experiment | null>(null)
    const [copyToProjectModalExperiment, setCopyToProjectModalExperiment] = useState<Experiment | null>(null)
    const [surveyModalExperiment, setSurveyModalExperiment] = useState<Experiment | null>(null)

    // Register feature flag creation tool so that it's always available on experiments page
    useMaxTool({
        identifier: 'create_feature_flag',
        initialMaxPrompt: 'Create a feature flag for ',
        suggestions: [],
        callback: () => {},
        active: true,
        context: {},
    })

    return (
        <SceneContent>
            <SceneTitleSection
                name="Experiments"
                resourceType={{
                    type: 'experiment',
                }}
                actions={
                    tab !== ExperimentsTabs.SharedMetrics && tab !== ExperimentsTabs.Holdouts ? (
                        <AccessControlAction
                            resourceType={AccessControlResourceType.Experiment}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <div className="flex items-center gap-2">
                                <MaxTool
                                    identifier="create_experiment"
                                    initialMaxPrompt="Create an experiment for "
                                    suggestions={[
                                        'Create an experiment to test…',
                                        'Set up an A/B test with a 70/30 split between control and test for…',
                                    ]}
                                    callback={(toolOutput: {
                                        experiment_id?: string | number
                                        experiment_name?: string
                                        feature_flag_key?: string
                                        error?: string
                                    }) => {
                                        if (toolOutput?.error || !toolOutput?.experiment_id) {
                                            lemonToast.error(
                                                `Failed to create experiment: ${toolOutput?.error || 'Unknown error'}`
                                            )
                                            return
                                        }
                                        // Refresh experiments list to show new experiment, then redirect to it
                                        loadExperiments()
                                        router.actions.push(urls.experiment(toolOutput.experiment_id))
                                    }}
                                    position="bottom-right"
                                    active={true}
                                    context={{}}
                                >
                                    <Shortcut
                                        name="NewExperiment"
                                        keybind={[keyBinds.new]}
                                        intent="New experiment"
                                        interaction="click"
                                        scope={Scene.Experiments}
                                    >
                                        <LemonButton
                                            size="small"
                                            type="primary"
                                            data-attr="create-experiment"
                                            to={urls.experiment('new')}
                                            tooltip="New experiment"
                                        >
                                            <span className="pr-3">New experiment</span>
                                        </LemonButton>
                                    </Shortcut>
                                </MaxTool>
                            </div>
                        </AccessControlAction>
                    ) : undefined
                }
            />
            <LemonTabs
                activeKey={tab}
                onChange={(newKey) => setExperimentsTab(newKey)}
                sceneInset
                tabs={[
                    {
                        key: ExperimentsTabs.All,
                        label: 'Experiments',
                        content: (
                            <ExperimentsTable
                                openDuplicateModal={setDuplicateModalExperiment}
                                openSurveyModal={setSurveyModalExperiment}
                                openCopyToProjectModal={setCopyToProjectModalExperiment}
                            />
                        ),
                    },
                    {
                        key: ExperimentsTabs.SharedMetrics,
                        label: 'Shared metrics',
                        content: <SharedMetrics />,
                    },
                    { key: ExperimentsTabs.Holdouts, label: 'Holdout groups', content: <Holdouts /> },
                    {
                        key: ExperimentsTabs.History,
                        label: 'History',
                        content: <ActivityLog scope={ActivityScope.EXPERIMENT} />,
                    },
                    {
                        key: ExperimentsTabs.Settings,
                        label: 'Settings',
                        content: <ExperimentsSettings />,
                    },
                ]}
            />
            {duplicateModalExperiment && (
                <DuplicateExperimentModal
                    isOpen={true}
                    onClose={() => setDuplicateModalExperiment(null)}
                    experiment={duplicateModalExperiment}
                />
            )}
            {copyToProjectModalExperiment && (
                <CopyExperimentToProjectModal
                    isOpen={true}
                    onClose={() => setCopyToProjectModalExperiment(null)}
                    experiment={copyToProjectModalExperiment}
                />
            )}
            {surveyModalExperiment && (
                <QuickSurveyModal
                    context={{ type: QuickSurveyType.EXPERIMENT, experiment: surveyModalExperiment }}
                    isOpen={true}
                    onCancel={() => setSurveyModalExperiment(null)}
                />
            )}
            {featureFlags[FEATURE_FLAGS.EXPERIMENTS_LIST_AA_TEST] === 'test' && (
                <div data-attr="experiments-list-aa-test-variant" className="hidden" />
            )}
        </SceneContent>
    )
}
