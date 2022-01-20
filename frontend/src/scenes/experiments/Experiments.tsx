import { PageHeader } from 'lib/components/PageHeader'
import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { experimentsLogic } from './experimentsLogic'
import { PlusOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { LemonTable, LemonTableColumn, LemonTableColumns } from '../../lib/components/LemonTable'
import { createdAtColumn, createdByColumn } from '../../lib/components/LemonTable/columnUtils'
import { Experiment, ExperimentsTabs } from '~/types'
import { normalizeColumnTitle } from 'lib/components/Table/utils'
import { urls } from 'scenes/urls'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { Link } from 'lib/components/Link'
import { LinkButton } from 'lib/components/LinkButton'
import { dayjs } from 'lib/dayjs'
import { Tabs, Tag } from 'antd'
import { More } from 'lib/components/LemonButton/More'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonSpacer } from 'lib/components/LemonRow'

export const scene: SceneExport = {
    component: Experiments,
    logic: experimentsLogic,
}

export function Experiments(): JSX.Element {
    const { experiments, experimentsLoading, tab } = useValues(experimentsLogic)
    const { setExperimentsFilters, deleteExperiment } = useActions(experimentsLogic)

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
                            <h4 className="row-name">{stringWithWBR(experiment.name, 17)}</h4>
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
            render: function Render(_, experiment: Experiment) {
                const duration = experiment.end_date
                    ? dayjs(experiment.end_date).diff(dayjs(experiment.start_date), 'day')
                    : experiment.start_date
                        ? dayjs().diff(dayjs(experiment.start_date), 'day')
                        : undefined

                return <div>{duration !== undefined ? `${duration} day${duration > 1 ? 's' : ''}` : 'N.A'}</div>
            },
        },
        {
            title: 'Status',
            render: function Render(_, experiment: Experiment) {
                const statusColors = { running: 'green', draft: 'default', complete: 'purple' }
                const status = (): string => {
                    if (!experiment.start_date) {
                        return 'draft'
                    } else if (!experiment.end_date) {
                        return 'running'
                    }
                    return 'complete'
                }
                return (
                    <Tag color={statusColors[status()]} style={{ fontWeight: 600 }}>
                        {status().toUpperCase()}
                    </Tag>
                )
            },
        },
        {
            width: 0,
            render: function Render(_, experiment: Experiment) {
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton type="stealth" to={urls.experiment(`${experiment.id}`)} compact fullWidth>
                                    View
                                </LemonButton>
                                <LemonSpacer />
                                <LemonButton
                                    type="stealth"
                                    style={{ color: 'var(--danger)' }}
                                    onClick={() => deleteExperiment(experiment.id)}
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
                title="Experiments"
                buttons={
                    <LinkButton
                        type="primary"
                        data-attr="create-experiment"
                        to={urls.experiment('new')}
                        icon={<PlusOutlined />}
                    >
                        New Experiment
                    </LinkButton>
                }
            />
            <Tabs
                activeKey={tab}
                style={{ borderColor: '#D9D9D9' }}
                onChange={(t) => setExperimentsFilters({ tab: t as ExperimentsTabs })}
            >
                <Tabs.TabPane tab="All Experiments" key={ExperimentsTabs.All} />
                <Tabs.TabPane tab="Your Experiments" key={ExperimentsTabs.Yours} />
                <Tabs.TabPane tab="Archived Experiments" key={ExperimentsTabs.Archived} />
            </Tabs>
            <LemonTable
                dataSource={experiments}
                columns={columns}
                rowKey="id"
                loading={experimentsLoading}
                defaultSorting={{ columnKey: 'id', order: 1 }}
                pagination={{ pageSize: 100 }}
                nouns={['Experiment', 'Experiments']}
                data-attr="experiment-table"
            />
        </div>
    )
}
