import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { experimentsLogic } from './experimentsLogic'
import { useActions, useValues } from 'kea'
import { LemonTable, LemonTableColumn, LemonTableColumns } from '../../lib/components/LemonTable'
import { createdAtColumn, createdByColumn } from '../../lib/components/LemonTable/columnUtils'
import { Experiment, ExperimentsTabs, AvailableFeature, ExperimentStatus } from '~/types'
import { normalizeColumnTitle } from 'lib/components/Table/utils'
import { urls } from 'scenes/urls'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { Link } from 'lib/components/Link'
import { dayjs } from 'lib/dayjs'
import { Tabs, Tag } from 'antd'
import { More } from 'lib/components/LemonButton/More'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonDivider } from 'lib/components/LemonDivider'
import { userLogic } from 'scenes/userLogic'
import { PayGatePage } from 'lib/components/PayGatePage/PayGatePage'
import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

export const scene: SceneExport = {
    component: Experiments,
    logic: experimentsLogic,
}

export function Experiments(): JSX.Element {
    const { filteredExperiments, experimentsLoading, tab, getExperimentStatus, searchTerm } =
        useValues(experimentsLogic)
    const { setExperimentsTab, deleteExperiment, setSearchStatus, setSearchTerm } = useActions(experimentsLogic)
    const { hasAvailableFeature } = useValues(userLogic)

    const getExperimentDuration = (experiment: Experiment): number | undefined => {
        return experiment.end_date
            ? dayjs(experiment.end_date).diff(dayjs(experiment.start_date), 'day')
            : experiment.start_date
            ? dayjs().diff(dayjs(experiment.start_date), 'day')
            : undefined
    }

    const columns: LemonTableColumns<Experiment> = [
        {
            title: normalizeColumnTitle('Name'),
            dataIndex: 'name',
            className: 'ph-no-capture',
            sticky: true,
            width: '40%',
            render: function Render(_, experiment: Experiment) {
                return (
                    <>
                        <Link to={experiment.id ? urls.experiment(experiment.id) : undefined}>
                            <span className="row-name">{stringWithWBR(experiment.name, 17)}</span>
                        </Link>
                        {experiment.description && <span className="row-description">{experiment.description}</span>}
                    </>
                )
            },
        },
        createdByColumn<Experiment>() as LemonTableColumn<Experiment, keyof Experiment | undefined>,
        createdAtColumn<Experiment>() as LemonTableColumn<Experiment, keyof Experiment | undefined>,
        {
            title: 'Duration',
            key: 'duration',
            render: function Render(_, experiment: Experiment) {
                const duration = getExperimentDuration(experiment)

                return <div>{duration !== undefined ? `${duration} day${duration !== 1 ? 's' : ''}` : '--'}</div>
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
                const statusColors = { running: 'green', draft: 'default', complete: 'purple' }
                const status = getExperimentStatus(experiment)
                return (
                    <Tag color={statusColors[status]} style={{ fontWeight: 600 }}>
                        {status.toUpperCase()}
                    </Tag>
                )
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
                                <LemonButton
                                    status="stealth"
                                    to={urls.experiment(`${experiment.id}`)}
                                    size="small"
                                    fullWidth
                                >
                                    View
                                </LemonButton>
                                <LemonDivider />
                                <LemonButton
                                    status="danger"
                                    onClick={() => deleteExperiment(experiment.id as number)}
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
                title={<div className="flex items-center">Experiments</div>}
                buttons={
                    hasAvailableFeature(AvailableFeature.EXPERIMENTATION) ? (
                        <LemonButton type="primary" data-attr="create-experiment" to={urls.experiment('new')}>
                            New experiment
                        </LemonButton>
                    ) : undefined
                }
            />
            {hasAvailableFeature(AvailableFeature.EXPERIMENTATION) ? (
                <>
                    <div className="mb-4">
                        Check out our
                        <Link
                            data-attr="experiment-help"
                            to="https://posthog.com/docs/user-guides/experimentation?utm_medium=in-product&utm_campaign=new-experiment"
                            target="_blank"
                        >
                            {' '}
                            Experimentation user guide
                        </Link>{' '}
                        to learn more.
                    </div>
                    <Tabs
                        activeKey={tab}
                        style={{ borderColor: '#D9D9D9' }}
                        onChange={(t) => setExperimentsTab(t as ExperimentsTabs)}
                    >
                        <Tabs.TabPane tab="All experiments" key={ExperimentsTabs.All} />
                        <Tabs.TabPane tab="Your experiments" key={ExperimentsTabs.Yours} />
                        <Tabs.TabPane tab="Archived experiments" key={ExperimentsTabs.Archived} />
                    </Tabs>
                    <div className="flex justify-between mb-4">
                        <LemonInput
                            type="search"
                            placeholder="Search for Experiments"
                            onChange={setSearchTerm}
                            value={searchTerm}
                        />
                        <div className="flex items-center gap-2">
                            <span>
                                <b>Status</b>
                            </span>
                            <LemonSelect
                                onChange={(status) => {
                                    if (status) {
                                        setSearchStatus(status as ExperimentStatus | 'all')
                                    }
                                }}
                                options={[
                                    { label: 'All', value: 'all' },
                                    { label: 'Draft', value: ExperimentStatus.Draft },
                                    { label: 'Running', value: ExperimentStatus.Running },
                                    { label: 'Complete', value: ExperimentStatus.Complete },
                                ]}
                                value="all"
                                dropdownMaxContentWidth
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
            ) : (
                <PayGatePage
                    featureKey={AvailableFeature.EXPERIMENTATION}
                    header={
                        <>
                            Introducing <span className="highlight">Experimentation</span>!
                        </>
                    }
                    caption="Improve your product by A/B testing new features to discover what works best for your users."
                    docsLink="https://posthog.com/docs/user-guides/experimentation"
                />
            )}
        </div>
    )
}
