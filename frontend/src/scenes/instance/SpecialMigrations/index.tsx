import './index.scss'

import React from 'react'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { Modal, Progress, Table } from 'antd'
import { useActions, useValues } from 'kea'
import { SpecialMigration, migrationStatusNumberToMessage, specialMigrationsLogic } from './specialMigrationsLogic'
import {
    PlayCircleOutlined,
    StopOutlined,
    RedoOutlined,
    CheckCircleOutlined,
    InfoCircleOutlined,
} from '@ant-design/icons'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { Tooltip } from 'lib/components/Tooltip'

export const scene: SceneExport = {
    component: SpecialMigrations,
}

export const tooltipMessageForStatus = {
    0: 'Run migration',
    1: 'Force stop migration',
    2: 'Migration completed',
    3: 'Re-run migration',
    4: 'Re-run migration',
}

export function SpecialMigrations(): JSX.Element {
    const { specialMigrations, specialMigrationsLoading } = useValues(specialMigrationsLogic)
    const { triggerMigration, forceStopMigration } = useActions(specialMigrationsLogic)

    const columns = [
        {
            title: '',
            render: function RenderTriggerButton(specialMigration: SpecialMigration): JSX.Element {
                const status = specialMigration.status
                return (
                    <Tooltip title={tooltipMessageForStatus[status]}>
                        {status === 0 ? (
                            <PlayCircleOutlined
                                className="migration-btn success"
                                onClick={() => triggerMigration(specialMigration.id)}
                            />
                        ) : status === 1 ? (
                            <StopOutlined
                                className="migration-btn danger"
                                onClick={() => forceStopMigration(specialMigration.id)}
                            />
                        ) : status === 2 ? (
                            <CheckCircleOutlined className="success" />
                        ) : (
                            <RedoOutlined
                                className="migration-btn warning"
                                onClick={() => triggerMigration(specialMigration.id)}
                            />
                        )}
                    </Tooltip>
                )
            },
        },
        {
            title: 'Migration name',
            dataIndex: 'name',
        },
        {
            title: 'Description',
            render: function RenderError(specialMigration: SpecialMigration): JSX.Element {
                const description = specialMigration.description
                return (
                    <small>
                        <span>{description.slice(0, 40)}</span>
                        {description.length > 40 ? (
                            <a
                                onClick={() => {
                                    Modal.info({
                                        title: `'${specialMigration.name}' description`,
                                        content: <pre>{description}</pre>,
                                        icon: <InfoCircleOutlined />,
                                        okText: 'Close',
                                        width: '80%',
                                    })
                                }}
                            >
                                {` [...]`}
                            </a>
                        ) : null}
                    </small>
                )
            },
        },
        {
            title: 'Progress',
            dataIndex: 'progress',
            render: function RenderMigrationProgress(progress: number): JSX.Element {
                return (
                    <div>
                        <Progress percent={progress} />
                    </div>
                )
            },
        },
        {
            title: 'Status',
            dataIndex: 'status',
            render: function RenderMigrationStatus(status: number): JSX.Element {
                return <div>{migrationStatusNumberToMessage[status]}</div>
            },
        },
        {
            title: 'Error',
            render: function RenderError(specialMigration: SpecialMigration): JSX.Element {
                const error = specialMigration.last_error || ''
                return (
                    <small>
                        <span>{error.slice(0, 40)}</span>
                        {error.length > 40 ? (
                            <a
                                onClick={() => {
                                    Modal.info({
                                        title: `Error on migration '${specialMigration.name}'`,
                                        content: <pre>{error}</pre>,
                                        icon: <InfoCircleOutlined />,
                                        okText: 'Close',
                                        width: '80%',
                                    })
                                }}
                            >
                                {` [...]`}
                            </a>
                        ) : null}
                    </small>
                )
            },
        },
        {
            title: 'Current operation index',
            dataIndex: 'current_operation_index',
        },
        {
            title: 'Current query ID',
            dataIndex: 'current_query_id',
            render: function RenderQueryId(queryId: string): JSX.Element {
                return (
                    <div>
                        <small>{queryId}</small>
                    </div>
                )
            },
        },
        {
            title: 'Celery task ID',
            dataIndex: 'celery_task_id',
            render: function RenderCeleryTaskId(celeryTaskId: string): JSX.Element {
                return (
                    <div>
                        <small>{celeryTaskId}</small>
                    </div>
                )
            },
        },
        {
            title: 'Started at',
            dataIndex: 'started_at',
            render: function RenderStartedAt(startedAt: string): JSX.Element {
                return <div>{humanFriendlyDetailedTime(startedAt)}</div>
            },
        },
        {
            title: 'Finished at',
            dataIndex: 'finished_at',
            render: function RenderFinishedAt(finishedAt: string): JSX.Element {
                return <div>{humanFriendlyDetailedTime(finishedAt)}</div>
            },
        },
    ]
    return (
        <div className="special-migrations-scene">
            <PageHeader title="Special Migrations" caption="Manage special migrations in your instance" />

            <Table
                pagination={{ pageSize: 99999, hideOnSinglePage: true }}
                loading={specialMigrationsLoading}
                columns={columns}
                dataSource={specialMigrations}
            />
        </div>
    )
}
