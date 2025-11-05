import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'
import { match } from 'ts-pattern'

import { LemonDialog, LemonInput, LemonSelect, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { MemberSelect } from 'lib/components/MemberSelect'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { ExperimentsHog } from 'lib/components/hedgehogs'
import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { atColumn, createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { useMaxTool } from 'scenes/max/useMaxTool'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import {
    AccessControlLevel,
    AccessControlResourceType,
    ActivityScope,
    Experiment,
    ExperimentsTabs,
    ProductKey,
    ProgressStatus,
} from '~/types'

import { DuplicateExperimentModal } from './DuplicateExperimentModal'
import { StatusTag, createMaxToolExperimentSurveyConfig } from './ExperimentView/components'
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

// Component for the survey button using MaxTool
const ExperimentSurveyButton = ({ experiment }: { experiment: Experiment }): JSX.Element => {
    const { user } = useValues(userLogic)
    const { openMax } = useMaxTool(createMaxToolExperimentSurveyConfig(experiment, user))

    // Don't show the button if there's no feature flag associated with the experiment
    if (!experiment.feature_flag) {
        return <></>
    }

    return (
        <LemonButton
            onClick={openMax || undefined}
            size="small"
            fullWidth
            data-attr="create-survey"
            disabled={!openMax}
        >
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
            <LemonInput
                type="search"
                placeholder="Search experiments"
                onChange={(search) => onFiltersChange({ search, page: 1 })}
                value={filters.search || ''}
            />
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
    )
}

const ExperimentsTable = ({
    openDuplicateModal,
}: {
    openDuplicateModal: (experiment: Experiment) => void
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
                                <ExperimentSurveyButton experiment={experiment} />
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
                        {`${startCount}${endCount - startCount > 1 ? '-' + endCount : ''} of ${count} experiment${
                            count === 1 ? '' : 's'
                        }`}
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
    const { setExperimentsTab } = useActions(experimentsLogic)

    const [duplicateModalExperiment, setDuplicateModalExperiment] = useState<Experiment | null>(null)

    return (
        <SceneContent>
            <SceneTitleSection
                name="Experiments"
                description={EXPERIMENTS_PRODUCT_DESCRIPTION}
                resourceType={{
                    type: 'experiment',
                }}
                actions={
                    <AccessControlAction
                        resourceType={AccessControlResourceType.Experiment}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            size="small"
                            type="primary"
                            data-attr="create-experiment"
                            to={urls.experiment('new')}
                        >
                            New experiment
                        </LemonButton>
                    </AccessControlAction>
                }
            />
            <SceneDivider />
            <LemonTabs
                activeKey={tab}
                onChange={(newKey) => setExperimentsTab(newKey)}
                sceneInset
                tabs={[
                    {
                        key: ExperimentsTabs.All,
                        label: 'All experiments',
                        content: <ExperimentsTable openDuplicateModal={setDuplicateModalExperiment} />,
                    },
                    {
                        key: ExperimentsTabs.Archived,
                        label: 'Archived experiments',
                        content: <ExperimentsTable openDuplicateModal={setDuplicateModalExperiment} />,
                    },
                    { key: ExperimentsTabs.Holdouts, label: 'Holdout groups', content: <Holdouts /> },
                    {
                        key: ExperimentsTabs.SharedMetrics,
                        label: 'Shared metrics',
                        content: <SharedMetrics />,
                    },
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
        </SceneContent>
    )
}
