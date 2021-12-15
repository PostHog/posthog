import { PageHeader } from 'lib/components/PageHeader'
import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { experimentsLogic } from './experimentsLogic'
import { PlusOutlined } from '@ant-design/icons'
import { useValues } from 'kea'
import { LemonTable, LemonTableColumn, LemonTableColumns } from '../../lib/components/LemonTable'
import { createdAtColumn, createdByColumn } from '../../lib/components/LemonTable/columnUtils'
import { Experiment } from '~/types'
import { normalizeColumnTitle } from 'lib/components/Table/utils'
import { urls } from 'scenes/urls'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { Link } from 'lib/components/Link'
import { LinkButton } from 'lib/components/LinkButton'
import dayjs from 'dayjs'
import { Tag } from 'antd'

export const scene: SceneExport = {
    component: Experiments,
    logic: experimentsLogic,
}

export function Experiments(): JSX.Element {
    const { experiments, experimentsLoading } = useValues(experimentsLogic)

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
                return (
                    <div>
                        {`${
                            experiment.end_date
                                ? dayjs(experiment.start_date).diff(dayjs(experiment.end_date), 'day')
                                : 0
                        }`}{' '}
                        days
                    </div>
                )
            },
        },
        {
            title: 'Status',
            render: function Render(_, experiment: Experiment) {
                const statusColors = { active: 'green', draft: 'red', complete: 'purple' }
                const status = (): string => {
                    if (!experiment.start_date) {
                        return 'draft'
                    } else if (!experiment.end_date) {
                        return 'active'
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
    ]

    return (
        <div>
            <PageHeader
                title="Experiments"
                style={{ borderBottom: '1px solid var(--border)', marginBottom: '1rem' }}
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
