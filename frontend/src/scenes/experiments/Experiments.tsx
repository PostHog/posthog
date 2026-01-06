import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'
import { match } from 'ts-pattern'

import { LemonDialog, LemonInput, LemonSelect, LemonTag, Tooltip, lemonToast } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { MemberSelect } from 'lib/components/MemberSelect'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { ExperimentsHog } from 'lib/components/hedgehogs'
import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { atColumn, createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { pluralize } from 'lib/utils'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { addProductIntentForCrossSell } from 'lib/utils/product-intents'
import stringWithWBR from 'lib/utils/stringWithWBR'
import MaxTool from 'scenes/max/MaxTool'
import { useMaxTool } from 'scenes/max/useMaxTool'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { QuickSurveyModal } from 'scenes/surveys/QuickSurveyModal'
import { QuickSurveyType } from 'scenes/surveys/quick-create/types'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import {
    AccessControlLevel,
    AccessControlResourceType,
    ActivityScope,
    Experiment,
    ExperimentsTabs,
    ProgressStatus,
} from '~/types'

import { DuplicateExperimentModal } from './DuplicateExperimentModal'
import { ExperimentVelocityStats } from './ExperimentVelocityStats'
import { StatusTag } from './ExperimentView/components'
import { ExperimentsSettings } from './ExperimentsSettings'
import { Holdouts } from './Holdouts'
import { SharedMetrics } from './SharedMetrics/SharedMetrics'
import { EXPERIMENTS_PER_PAGE, ExperimentsFilters, experimentsLogic, getExperimentStatus } from './experimentsLogic'
import { isLegacyExperiment } from './utils'

export const scene: SceneExport = {
    component: Experiments,
    logic: experimentsLogic,
}

export const EXPERIMENTS_PRODUCT_DESCRIPTION =
    'Experiments help you test changes to your product to see which changes will lead to optimal results. Automatic statistical calculations let you see if the results are valid or if they are likely just a chance occurrence.'

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
    tab,
    filters,
    onFiltersChange,
}: {
    tab: ExperimentsTabs
    filters: ExperimentsFilters
    onFiltersChange: (filters: ExperimentsFilters, replace?: boolean) => void
}): JSX.Element => {
    return (
        <div className="flex justify-between gap-2 flex-wrap">
            <div className="flex items-center gap-6">
                <AppShortcut
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
                </AppShortcut>
                <div className="flex items-center gap-2">
                    {ExperimentsTabs.Archived !== tab && (
                        <>
                            <span>
                                <b>Status</b>
                            </span>
                            <LemonSelect
                                size="small"
                                onChange={(status) => {
                                    if (status === 'all') {
                                        const { status: _, ...restFilters } = filters
                                        onFiltersChange({ ...restFilters, page: 1 }, true)
                                    } else {
                                        onFiltersChange({ status: status as ProgressStatus, page: 1 })
                                    }
                                }}
                                options={
                                    [
                                        { label: 'All', value: 'all' },
                                        { label: 'Draft', value: ProgressStatus.Draft },
                                        { label: 'Running', value: ProgressStatus.Running },
                                        { label: 'Complete', value: ProgressStatus.Complete },
                                    ] as { label: string; value: string }[]
                                }
                                value={filters.status ?? 'all'}
                                dropdownMatchSelectWidth={false}
                                dropdownMaxContentWidth
                            />
                        </>
                    )}
                    <span className="ml-1">
                        <b>Created by</b>
                    </span>
                    <MemberSelect
                        defaultLabel="Any user"
                        value={filters.created_by_id ?? null}
                        onChange={(user) => {
                            if (!user) {
                                const { created_by_id, ...restFilters } = filters
                                onFiltersChange({ ...restFilters, page: 1 }, true)
                            } else {
                                onFiltersChange({ created_by_id: user.id, page: 1 })
                            }
                        }}
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
}: {
    openDuplicateModal: (experiment: Experiment) => void
    openSurveyModal: (experiment: Experiment) => void
}): JSX.Element => {
    const { currentProjectId, experiments, experimentsLoading, tab, shouldShowEmptyState, filters, count, pagination } =
        useValues(experimentsLogic)
    const { loadExperiments, archiveExperiment, setExperimentsFilters } = useActions(experimentsLogic)

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
                                {isLegacyExperiment(experiment) && (
                                    <Tooltip
                                        title="This experiment uses the legacy engine, so some features and improvements may be missing."
                                        docLink="https://posthog.com/docs/experiments/new-experimentation-engine"
                                    >
                                        <LemonTag type="warning" className="ml-1">
                                            Legacy
                                        </LemonTag>
                                    </Tooltip>
                                )}
                            </>
                        }
                        description={experiment.description}
                    />
                )
            },
        },
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
                const remainingDays = experiment.parameters?.recommended_running_time
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

                const score = {
                    draft: 1,
                    running: 2,
                    complete: 3,
                }
                return score[statusA] > score[statusB] ? 1 : -1
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
                                <LemonButton onClick={() => openDuplicateModal(experiment)} size="small" fullWidth>
                                    Duplicate
                                </LemonButton>
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
                                {!experiment.archived &&
                                    experiment?.end_date &&
                                    dayjs().isSameOrAfter(dayjs(experiment.end_date), 'day') && (
                                        <AccessControlAction
                                            resourceType={AccessControlResourceType.Experiment}
                                            minAccessLevel={AccessControlLevel.Editor}
                                            userAccessLevel={experiment.user_access_level}
                                        >
                                            <LemonButton
                                                onClick={() => {
                                                    LemonDialog.open({
                                                        title: 'Archive this experiment?',
                                                        content: (
                                                            <div className="text-sm text-secondary">
                                                                This action will move the experiment to the archived
                                                                tab. It can be restored at any time.
                                                            </div>
                                                        ),
                                                        primaryButton: {
                                                            children: 'Archive',
                                                            type: 'primary',
                                                            onClick: () => archiveExperiment(experiment.id as number),
                                                            size: 'small',
                                                        },
                                                        secondaryButton: {
                                                            children: 'Cancel',
                                                            type: 'tertiary',
                                                            size: 'small',
                                                        },
                                                    })
                                                }}
                                                data-attr={`experiment-${experiment.id}-dropdown-archive`}
                                                fullWidth
                                            >
                                                Archive experiment
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
                                        onClick={() => {
                                            LemonDialog.open({
                                                title: 'Delete this experiment?',
                                                content: (
                                                    <div className="text-sm text-secondary">
                                                        Experiment with its settings will be deleted, but event data
                                                        will be preserved.
                                                    </div>
                                                ),
                                                primaryButton: {
                                                    children: 'Delete',
                                                    type: 'primary',
                                                    onClick: () => {
                                                        void deleteWithUndo({
                                                            endpoint: `projects/${currentProjectId}/experiments`,
                                                            object: { name: experiment.name, id: experiment.id },
                                                            callback: () => {
                                                                loadExperiments()
                                                            },
                                                        })
                                                    },
                                                    size: 'small',
                                                },
                                                secondaryButton: {
                                                    children: 'Cancel',
                                                    type: 'tertiary',
                                                    size: 'small',
                                                },
                                            })
                                        }}
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
            {match(tab)
                .with(ExperimentsTabs.All, () => (
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
                            customHog={ExperimentsHog}
                            className="my-0"
                        />
                    </AccessControlAction>
                ))
                .with(ExperimentsTabs.Archived, () => (
                    <AccessControlAction
                        resourceType={AccessControlResourceType.Experiment}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <ProductIntroduction
                            productName="Experiments"
                            productKey={ProductKey.EXPERIMENTS}
                            thingName="archived experiment"
                            description={EXPERIMENTS_PRODUCT_DESCRIPTION}
                            docsURL="https://posthog.com/docs/experiments"
                            isEmpty={shouldShowEmptyState}
                            className="my-0"
                        />
                    </AccessControlAction>
                ))
                .otherwise(() => null)}
            <ExperimentsTableFilters tab={tab} filters={filters} onFiltersChange={setExperimentsFilters} />
            <LemonDivider className="my-0" />
            {count ? (
                <div>
                    <span className="text-secondary">
                        {`${startCount}${endCount - startCount > 1 ? '-' + endCount : ''} of ${pluralize(count, 'experiment')}`}
                    </span>
                </div>
            ) : null}
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
                        order: newSorting ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}` : undefined,
                        page: 1,
                    })
                }
            />
        </SceneContent>
    )
}

export function Experiments(): JSX.Element {
    const { tab } = useValues(experimentsLogic)
    const { setExperimentsTab, loadExperiments } = useActions(experimentsLogic)

    const [duplicateModalExperiment, setDuplicateModalExperiment] = useState<Experiment | null>(null)
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
                                <AppShortcut
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
                                </AppShortcut>
                            </MaxTool>
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
                        label: 'All experiments',
                        content: (
                            <ExperimentsTable
                                openDuplicateModal={setDuplicateModalExperiment}
                                openSurveyModal={setSurveyModalExperiment}
                            />
                        ),
                    },
                    {
                        key: ExperimentsTabs.Archived,
                        label: 'Archived experiments',
                        content: (
                            <ExperimentsTable
                                openDuplicateModal={setDuplicateModalExperiment}
                                openSurveyModal={setSurveyModalExperiment}
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
            {surveyModalExperiment && (
                <QuickSurveyModal
                    context={{ type: QuickSurveyType.EXPERIMENT, experiment: surveyModalExperiment }}
                    isOpen={true}
                    onCancel={() => setSurveyModalExperiment(null)}
                />
            )}
        </SceneContent>
    )
}
