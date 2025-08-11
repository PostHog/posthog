import { LemonDialog, LemonInput, LemonSelect, LemonTag, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { ExperimentsHog } from 'lib/components/hedgehogs'
import { MemberSelect } from 'lib/components/MemberSelect'
import { PageHeader } from 'lib/components/PageHeader'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { atColumn, createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { Link } from 'lib/lemon-ui/Link'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { useState } from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { match } from 'ts-pattern'
import { ActivityScope, Experiment, ExperimentsTabs, ProductKey, ProgressStatus } from '~/types'
import { ExperimentsSettings } from './ExperimentsSettings'

import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { DuplicateExperimentModal } from './DuplicateExperimentModal'
import { EXPERIMENTS_PER_PAGE, ExperimentsFilters, experimentsLogic, getExperimentStatus } from './experimentsLogic'
import { StatusTag } from './ExperimentView/components'
import { Holdouts } from './Holdouts'
import { isLegacyExperiment } from './utils'

export const scene: SceneExport = {
    component: Experiments,
    logic: experimentsLogic,
}

const EXPERIMENTS_PRODUCT_DESCRIPTION =
    'Experiments help you test changes to your product to see which changes will lead to optimal results. Automatic statistical calculations let you see if the results are valid or if they are likely just a chance occurrence.'

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
        <div className="flex justify-between mb-4 gap-2 flex-wrap">
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
                                <LemonButton
                                    onClick={() => {
                                        if (experiment.feature_flag?.id) {
                                            featureFlagLogic({ id: experiment.feature_flag.id }).mount()
                                            featureFlagLogic({ id: experiment.feature_flag.id }).actions.createSurvey()
                                        }
                                    }}
                                    size="small"
                                    fullWidth
                                    data-attr="create-survey"
                                    disabled={!experiment.feature_flag?.id}
                                >
                                    Create survey
                                </LemonButton>
                                {!experiment.archived &&
                                    experiment?.end_date &&
                                    dayjs().isSameOrAfter(dayjs(experiment.end_date), 'day') && (
                                        <LemonButton
                                            onClick={() => {
                                                LemonDialog.open({
                                                    title: 'Archive this experiment?',
                                                    content: (
                                                        <div className="text-sm text-secondary">
                                                            This action will move the experiment to the archived tab. It
                                                            can be restored at any time.
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
                                    )}
                                <LemonDivider />
                                <LemonButton
                                    status="danger"
                                    onClick={() => {
                                        LemonDialog.open({
                                            title: 'Delete this experiment?',
                                            content: (
                                                <div className="text-sm text-secondary">
                                                    Experiment with its settings will be deleted, but event data will be
                                                    preserved.
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
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <div>
            {match(tab)
                .with(ExperimentsTabs.All, () => (
                    <ProductIntroduction
                        productName="Experiments"
                        productKey={ProductKey.EXPERIMENTS}
                        thingName="experiment"
                        description={EXPERIMENTS_PRODUCT_DESCRIPTION}
                        docsURL="https://posthog.com/docs/experiments"
                        action={() => router.actions.push(urls.experiment('new'))}
                        isEmpty={shouldShowEmptyState}
                        customHog={ExperimentsHog}
                    />
                ))
                .with(ExperimentsTabs.Archived, () => (
                    <ProductIntroduction
                        productName="Experiments"
                        productKey={ProductKey.EXPERIMENTS}
                        thingName="archived experiment"
                        description={EXPERIMENTS_PRODUCT_DESCRIPTION}
                        docsURL="https://posthog.com/docs/experiments"
                        isEmpty={shouldShowEmptyState}
                    />
                ))
                .otherwise(() => null)}
            <ExperimentsTableFilters tab={tab} filters={filters} onFiltersChange={setExperimentsFilters} />
            <LemonDivider className="my-4" />
            <div className="mb-4">
                <span className="text-secondary">
                    {count
                        ? `${startCount}${endCount - startCount > 1 ? '-' + endCount : ''} of ${count} experiment${
                              count === 1 ? '' : 's'
                          }`
                        : null}
                </span>
            </div>
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
        </div>
    )
}

export function Experiments(): JSX.Element {
    const { tab } = useValues(experimentsLogic)
    const { setExperimentsTab } = useActions(experimentsLogic)

    const [duplicateModalExperiment, setDuplicateModalExperiment] = useState<Experiment | null>(null)

    return (
        <div>
            <PageHeader
                buttons={
                    <LemonButton type="primary" data-attr="create-experiment" to={urls.experiment('new')}>
                        New experiment
                    </LemonButton>
                }
                caption={
                    <>
                        <Link
                            data-attr="experiment-help"
                            to="https://posthog.com/docs/experiments/installation?utm_medium=in-product&utm_campaign=new-experiment"
                            target="_blank"
                        >
                            &nbsp; Visit the guide
                        </Link>
                        &nbsp; to learn more.
                    </>
                }
                tabbedPage={true}
            />
            <LemonTabs
                activeKey={tab}
                onChange={(newKey) => setExperimentsTab(newKey)}
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
                        link: urls.experimentsSharedMetrics(),
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
        </div>
    )
}
