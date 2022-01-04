import './index.scss'

import React from 'react'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { Button, Modal, Progress, Space, Table, Tabs } from 'antd'
import { useActions, useValues } from 'kea'
import {
    AsyncMigration,
    migrationStatusNumberToMessage,
    asyncMigrationsLogic,
    AsyncMigrationsTab,
    AsyncMigrationStatus,
} from './asyncMigrationsLogic'
import {
    PlayCircleOutlined,
    StopOutlined,
    RedoOutlined,
    CheckCircleOutlined,
    InfoCircleOutlined,
} from '@ant-design/icons'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { Tooltip } from 'lib/components/Tooltip'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { userLogic } from 'scenes/userLogic'
import { SettingUpdateField } from './SettingUpdateField'

export const scene: SceneExport = {
    component: AsyncMigrations,
}

const { TabPane } = Tabs

export function AsyncMigrations(): JSX.Element {
    const { user } = useValues(userLogic)
    const { asyncMigrations, asyncMigrationsLoading, activeTab, asyncMigrationSettings } =
        useValues(asyncMigrationsLogic)
    const {
        triggerMigration,
        resumeMigration,
        rollbackMigration,
        forceStopMigration,
        forceStopMigrationWithoutRollback,
        loadAsyncMigrations,
        setActiveTab,
    } = useActions(asyncMigrationsLogic)

    const columns = [
        {
            title: '',
            render: function RenderTriggerButton(asyncMigration: AsyncMigration): JSX.Element {
                const status = asyncMigration.status
                return (
                    <div>
                        {status === AsyncMigrationStatus.NotStarted ? (
                            <Tooltip title="Run migration">
                                <PlayCircleOutlined
                                    className="migration-btn success"
                                    onClick={() => triggerMigration(asyncMigration.id)}
                                />
                            </Tooltip>
                        ) : status === AsyncMigrationStatus.Running ? (
                            <div>
                                <Tooltip title="Force stop migration">
                                    <StopOutlined
                                        className="migration-btn danger"
                                        onClick={() => forceStopMigration(asyncMigration.id)}
                                    />
                                </Tooltip>
                                <Tooltip title="Force stop migration without rollback">
                                    <StopOutlined
                                        className="migration-btn danger"
                                        onClick={() => forceStopMigrationWithoutRollback(asyncMigration.id)}
                                    />
                                </Tooltip>
                            </div>
                        ) : status === AsyncMigrationStatus.CompletedSuccessfully ? (
                            <Tooltip title="Migration Completed">
                                <CheckCircleOutlined className="success" />
                            </Tooltip>
                        ) : status === AsyncMigrationStatus.Errored ? (
                            <div>
                                <Tooltip title="Resume migration">
                                    <PlayCircleOutlined
                                        className="migration-btn success"
                                        onClick={() => resumeMigration(asyncMigration.id)}
                                    />
                                </Tooltip>
                                <Tooltip title="Restart migration without rollback">
                                    <RedoOutlined
                                        className="migration-btn warning"
                                        onClick={() => triggerMigration(asyncMigration.id)}
                                    />
                                </Tooltip>
                                <Tooltip title="Rollback migration">
                                    <RedoOutlined
                                        className="migration-btn warning"
                                        onClick={() => rollbackMigration(asyncMigration.id)}
                                    />
                                </Tooltip>
                            </div>
                        ) : status === AsyncMigrationStatus.RolledBack ? (
                            <Tooltip title="Restart migration">
                                <RedoOutlined
                                    className="migration-btn warning"
                                    onClick={() => triggerMigration(asyncMigration.id)}
                                />
                            </Tooltip>
                        ) : status === AsyncMigrationStatus.Starting ? (
                            <Spinner size="sm" />
                        ) : (
                            <Spinner size="sm" />
                        )}
                    </div>
                )
            },
        },
        {
            title: 'Migration name',
            dataIndex: 'name',
        },
        {
            title: 'Description',
            render: function RenderError(asyncMigration: AsyncMigration): JSX.Element {
                const description = asyncMigration.description
                return (
                    <small>
                        <span>{description.slice(0, 40)}</span>
                        {description.length > 40 ? (
                            <a
                                onClick={() => {
                                    Modal.info({
                                        title: `'${asyncMigration.name}' description`,
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
            title: 'Last operation index',
            dataIndex: 'current_operation_index',
        },
        {
            title: 'Last query ID',
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
        <div className="async-migrations-scene">
            {user?.is_staff ? (
                <>
                    <PageHeader
                        title="Async Migrations"
                        caption={
                            <>
                                <p>Manage async migrations in your instance.</p>
                                <p>
                                    Read about async migrations on our{' '}
                                    <a href="https://posthog.com/docs/self-host/configure/async-migrations">
                                        dedicated docs page
                                    </a>
                                    .
                                </p>
                            </>
                        }
                    />

                    <Tabs activeKey={activeTab} onChange={(t) => setActiveTab(t as AsyncMigrationsTab)}>
                        <TabPane tab="Management" key={AsyncMigrationsTab.Management} />
                        <TabPane tab="Settings" key={AsyncMigrationsTab.Settings} />
                    </Tabs>

                    {activeTab === AsyncMigrationsTab.Management ? (
                        <>
                            <div className="mb float-right">
                                <Button
                                    icon={asyncMigrationsLoading ? <Spinner size="sm" /> : <RedoOutlined />}
                                    onClick={loadAsyncMigrations}
                                >
                                    Refresh
                                </Button>
                            </div>
                            <Space />
                            <Table
                                pagination={false}
                                loading={asyncMigrationsLoading}
                                columns={columns}
                                dataSource={asyncMigrations}
                            />
                        </>
                    ) : activeTab === AsyncMigrationsTab.Settings ? (
                        <>
                            <br />
                            {asyncMigrationSettings.map((setting) => {
                                return (
                                    <div key={setting.key}>
                                        <SettingUpdateField setting={setting} />
                                    </div>
                                )
                            })}
                        </>
                    ) : null}
                </>
            ) : (
                <PageHeader
                    title="Async Migrations"
                    caption={
                        <>
                            <p>
                                Only users with staff access can manage async migrations. Please contact your instance
                                admin.
                            </p>
                            <p>
                                If you're an admin and don't have access, set <code>is_staff=true</code> for your user
                                on the PostgreSQL <code>posthog_user</code> table.
                            </p>
                        </>
                    }
                />
            )}
        </div>
    )
}
