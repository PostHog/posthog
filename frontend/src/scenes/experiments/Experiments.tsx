import { PageHeader } from 'lib/components/PageHeader'
import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { experimentsLogic } from './experimentsLogic'
import { PlusOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { LemonTable, LemonTableColumn, LemonTableColumns } from '../../lib/components/LemonTable'
import { createdAtColumn, createdByColumn } from '../../lib/components/LemonTable/columnUtils'
import { Experiment } from '~/types'
import { normalizeColumnTitle } from 'lib/components/Table/utils'
import { urls } from 'scenes/urls'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { Link } from 'lib/components/Link'
import { TZLabel } from 'lib/components/TimezoneAware'
import { LinkButton } from 'lib/components/LinkButton'
import dayjs from 'dayjs'
import { LemonButton } from 'lib/components/LemonButton'
import { Popconfirm } from 'antd'
import { DeleteOutlined } from '@ant-design/icons'

export const scene: SceneExport = {
    component: Experiments,
    logic: experimentsLogic,
}

export function Experiments(): JSX.Element {
    const { experiments, experimentsLoading } = useValues(experimentsLogic)
    const { deleteExperiment } = useActions(experimentsLogic)

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
        {
            title: 'Start Date',
            dataIndex: 'start_date',
            render: function RenderStartDate(_, experiment: Experiment) {
                return experiment.start_date ? (
                    <div style={{ whiteSpace: 'nowrap' }}>
                        <TZLabel time={experiment.start_date} />
                    </div>
                ) : (
                    <span style={{ color: 'var(--muted)' }}>Draft</span>
                )
            },
            sorter: (a, b) => (new Date(a.start_date || 0) > new Date(b.start_date || 0) ? 1 : -1),
        },
        {
            title: 'Days Running',
            render: function Render(_, experiment: Experiment) {
                return experiment.end_date ? (
                    <div>{dayjs(experiment.start_date).diff(dayjs(experiment.end_date), 'day')}</div>
                ) : (
                    <div>0</div>
                )
            },
        },
        createdByColumn<Experiment>() as LemonTableColumn<Experiment, keyof Experiment | undefined>,
        createdAtColumn<Experiment>() as LemonTableColumn<Experiment, keyof Experiment | undefined>,
        {
            width: 0,
            render: function Render(_, experiment: Experiment) {
                return (
                    <Popconfirm
                        title="Are you sure you wish to delete this experiment? This will end the experiment and delete any associated feature flags."
                        onConfirm={() => deleteExperiment(experiment.id)}
                        okText="Delete"
                        cancelText="Cancel"
                        className="plugins-popconfirm"
                    >
                        <LemonButton
                            style={{ color: 'var(--danger)', padding: 4 }}
                            type="stealth"
                            icon={<DeleteOutlined style={{ color: 'var(--danger)', fontSize: 16 }} />}
                            data-attr="plugin-uninstall"
                        />
                    </Popconfirm>
                )
            },
        },
    ]

    return (
        <div>
            <PageHeader title="Experiments" caption="Experiments" />
            <div className="mb float-right">
                <LinkButton
                    type="primary"
                    data-attr="create-experiment"
                    to={urls.experiment('new')}
                    icon={<PlusOutlined />}
                >
                    New Experiment
                </LinkButton>
            </div>
            <LemonTable
                dataSource={experiments}
                columns={columns}
                rowKey="id"
                loading={experimentsLoading}
                defaultSorting={{ columnKey: 'id', order: 1 }}
                pagination={{ pageSize: 20 }}
                nouns={['Experiment', 'Experiments']}
                data-attr="experiment-table"
            />
        </div>
    )
}
