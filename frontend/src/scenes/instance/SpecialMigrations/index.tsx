import './index.scss'

import React from 'react'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { Progress, Table } from 'antd'
import { useValues } from 'kea'
import { specialMigrationsLogic } from './specialMigrationsLogic'
import { PlayCircleOutlined, StopOutlined } from '@ant-design/icons'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { SystemStatusSubrows } from '~/types'

const migrationStatusNumberToMessage = {
    0: 'Not started',
    1: 'Running',
    2: 'Completed successfully',
    3: 'Errored',
    4: 'Rolled back',
}

export const scene: SceneExport = {
    component: SpecialMigrations,
}

export function SpecialMigrations(): JSX.Element {
    const { specialMigrations, specialMigrationsLoading } = useValues(specialMigrationsLogic)
    const columns = [
        {
            title: '',
            render: function RenderTriggerButton(specialMigration: Record<string, any>): JSX.Element {
                return (
                    <div>
                        {specialMigration.status === 0 ? (
                            <PlayCircleOutlined className="trigger-migration-button" onClick={() => {}} />
                        ) : specialMigration.status === 1 ? (
                            <StopOutlined className="force-stop-migration-button" onClick={() => {}} />
                        ) : null}
                    </div>
                )
            },
        },
        {
            title: 'Migration name',
            dataIndex: 'name',
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
            dataIndex: 'error',
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
        <div className="system-status-scene">
            <PageHeader title="Special Migrations" caption="Manage special migrations in your instance" />

            <Table
                pagination={{ pageSize: 99999, hideOnSinglePage: true }}
                loading={specialMigrationsLoading}
                expandable={{
                    expandedRowRender: function renderExpand(row) {
                        return row.subrows ? <Subrows {...row.subrows} /> : null
                    },
                    rowExpandable: (row) => !!row.subrows && row.subrows.rows.length > 0,
                    expandRowByClick: true,
                }}
                columns={columns}
                dataSource={specialMigrations || []}
            />
        </div>
    )
}

function Subrows(props: SystemStatusSubrows): JSX.Element {
    return (
        <Table
            rowKey="metric"
            pagination={{ pageSize: 99999, hideOnSinglePage: true }}
            dataSource={props.rows}
            columns={props.columns.map((title, dataIndex) => ({ title, dataIndex }))}
        />
    )
}
