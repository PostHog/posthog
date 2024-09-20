import { LemonDialog, LemonInput, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
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
import stringWithWBR from 'lib/utils/stringWithWBR'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Experiment, ExperimentsTabs, ProductKey, ProgressStatus } from '~/types'

import { experimentsLogic, getExperimentStatus } from './experimentsLogic'
import { StatusTag } from './ExperimentView/components'

export const scene: SceneExport = {
    component: Experiments,
    logic: experimentsLogic,
}

export function Experiments(): JSX.Element {
    const { filteredExperiments, experimentsLoading, tab, searchTerm, shouldShowEmptyState, searchStatus, userFilter } =
        useValues(experimentsLogic)
    const { setExperimentsTab, deleteExperiment, archiveExperiment, setSearchStatus, setSearchTerm, setUserFilter } =
        useActions(experimentsLogic)

    const EXPERIMENTS_PRODUCT_DESCRIPTION =
        'Experiments help you test changes to your product to see which changes will lead to optimal results. Automatic statistical calculations let you see if the results are valid or if they are likely just a chance occurrence.'

    const getExperimentDuration = (experiment: Experiment): number | undefined => {
        return experiment.end_date
            ? dayjs(experiment.end_date).diff(dayjs(experiment.start_date), 'day')
            : experiment.start_date
            ? dayjs().diff(dayjs(experiment.start_date), 'day')
            : undefined
    }

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
                        title={stringWithWBR(experiment.name, 17)}
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
                return <StatusTag experiment={experiment} />
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
                                {!experiment.archived &&
                                    experiment?.end_date &&
                                    dayjs().isSameOrAfter(dayjs(experiment.end_date), 'day') && (
                                        <LemonButton
                                            onClick={() => {
                                                LemonDialog.open({
                                                    title: 'Archive this experiment?',
                                                    content: (
                                                        <div className="text-sm text-muted">
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
                                                <div className="text-sm text-muted">
                                                    This action cannot be undone. All experiment data will be
                                                    permanently removed.
                                                </div>
                                            ),
                                            primaryButton: {
                                                children: 'Delete',
                                                type: 'primary',
                                                onClick: () => deleteExperiment(experiment.id as number),
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
                            {' '}
                            Visit the guide
                        </Link>{' '}
                        to learn more.
                    </>
                }
                tabbedPage={true}
            />
            <LemonTabs
                activeKey={tab}
                onChange={(newKey) => setExperimentsTab(newKey)}
                tabs={[
                    { key: ExperimentsTabs.All, label: 'All experiments' },
                    { key: ExperimentsTabs.Yours, label: 'Your experiments' },
                    { key: ExperimentsTabs.Archived, label: 'Archived experiments' },
                ]}
            />
            {tab === ExperimentsTabs.Archived ? (
                <ProductIntroduction
                    productName="Experiments"
                    productKey={ProductKey.EXPERIMENTS}
                    thingName="archived experiment"
                    description={EXPERIMENTS_PRODUCT_DESCRIPTION}
                    docsURL="https://posthog.com/docs/experiments"
                    isEmpty={shouldShowEmptyState}
                />
            ) : (
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
            )}
            {!shouldShowEmptyState && (
                <>
                    <div className="flex justify-between mb-4 gap-2 flex-wrap">
                        <LemonInput
                            type="search"
                            placeholder="Search experiments"
                            onChange={setSearchTerm}
                            value={searchTerm}
                        />
                        <div className="flex items-center gap-2">
                            <span>
                                <b>Status</b>
                            </span>
                            <LemonSelect
                                size="small"
                                onChange={(status) => {
                                    if (status) {
                                        setSearchStatus(status as ProgressStatus | 'all')
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
                                value={searchStatus ?? 'all'}
                                dropdownMatchSelectWidth={false}
                                dropdownMaxContentWidth
                            />
                            <span className="ml-1">
                                <b>Created by</b>
                            </span>
                            <MemberSelect
                                defaultLabel="Any user"
                                value={userFilter ?? null}
                                onChange={(user) => setUserFilter(user?.uuid ?? null)}
                            />
                        </div>
                    </div>
                    <LemonTable
                        dataSource={filteredExperiments}
                        columns={columns}
                        rowKey="id"
                        loading={experimentsLoading}
                        defaultSorting={{
                            columnKey: 'created_at',
                            order: -1,
                        }}
                        noSortingCancellation
                        pagination={{ pageSize: 100 }}
                        nouns={['experiment', 'experiments']}
                        data-attr="experiment-table"
                    />
                </>
            )}
        </div>
    )
}
