import { PageHeader } from 'lib/components/PageHeader'
import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { experimentsLogic } from './experimentsLogic'
import { PlusOutlined } from '@ant-design/icons'
import { useValues } from 'kea'
import { LemonTable, LemonTableColumn, LemonTableColumns } from '../../lib/components/LemonTable'
import { createdAtColumn, createdByColumn } from '../../lib/components/LemonTable/columnUtils'
import { AvailableFeature, Experiment } from '~/types'
import { normalizeColumnTitle } from 'lib/components/Table/utils'
import { urls } from 'scenes/urls'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { Link } from 'lib/components/Link'
import { LinkButton } from 'lib/components/LinkButton'
import { dayjs } from 'lib/dayjs'
import { Tag } from 'antd'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { userLogic } from 'scenes/userLogic'
import { PayGatePage } from 'lib/components/PayGatePage/PayGatePage'

export const scene: SceneExport = {
    component: Experiments,
    logic: experimentsLogic,
}

export function Experiments(): JSX.Element {
    const { experiments, experimentsLoading } = useValues(experimentsLogic)
    const { hasAvailableFeature } = useValues(userLogic)

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
    ]

    return (
        <div>
            <PageHeader
                title={
                    <div className="flex-center">
                        Experimentation
                        <LemonTag type="warning" style={{ marginLeft: 6, lineHeight: '1.4em' }}>
                            BETA
                        </LemonTag>
                    </div>
                }
                style={{ borderBottom: '1px solid var(--border)', paddingBottom: '0.5rem', marginBottom: '1rem' }}
                buttons={
                    hasAvailableFeature(AvailableFeature.EXPERIMENTATION) ? (
                        <LinkButton
                            type="primary"
                            data-attr="create-experiment"
                            to={urls.experiment('new')}
                            icon={<PlusOutlined />}
                        >
                            New Experiment
                        </LinkButton>
                    ) : undefined
                }
            />
            {hasAvailableFeature(AvailableFeature.EXPERIMENTATION) ? (
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
            ) : (
                <PayGatePage
                    featureKey="experimentation"
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
