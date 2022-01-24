import './AsyncMigrations.scss'

import React from 'react'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { Button, Modal, Progress, Space, Tabs } from 'antd'
import { useActions, useValues } from 'kea'
import {
    AsyncMigration,
    migrationStatusNumberToMessage,
    asyncMigrationsLogic,
    AsyncMigrationsTab,
    AsyncMigrationStatus,
} from './asyncMigrationsLogic'
import { PlayCircleOutlined, RedoOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { Tooltip } from 'lib/components/Tooltip'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { userLogic } from 'scenes/userLogic'
import { SettingUpdateField } from './SettingUpdateField'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { AsyncMigrationDetails } from './AsyncMigrationDetails'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { More } from 'lib/components/LemonButton/More'
import { LemonButton } from 'lib/components/LemonButton'

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
        loadAsyncMigrationErrors,
        setActiveTab,
    } = useActions(asyncMigrationsLogic)

    const columns: LemonTableColumns<AsyncMigration> = [
        {
            title: 'id',
            dataIndex: 'id',
        },
        {
            title: 'Migration name',
            dataIndex: 'name',
        },
        {
            title: 'Description',
            render: function Render(_, asyncMigration: AsyncMigration): JSX.Element {
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
            render: function Render(_, asyncMigration: AsyncMigration): JSX.Element {
                const progress = asyncMigration.progress
                return (
                    <div>
                        <Progress percent={progress} />
                    </div>
                )
            },
        },
        {
            title: 'Status',
            render: function Render(_, asyncMigration: AsyncMigration): JSX.Element {
                const status = asyncMigration.status
                return <div>{migrationStatusNumberToMessage[status]}</div>
            },
        },
        {
            title: 'Last operation index',
            dataIndex: 'current_operation_index',
        },
        {
            title: 'Last query ID',
            render: function Render(_, asyncMigration: AsyncMigration): JSX.Element {
                return (
                    <div>
                        <small>{asyncMigration.current_query_id}</small>
                    </div>
                )
            },
        },
        {
            title: 'Started at',
            render: function Render(_, asyncMigration: AsyncMigration): JSX.Element {
                const startedAt = asyncMigration.started_at
                return <div>{humanFriendlyDetailedTime(startedAt)}</div>
            },
        },
        {
            title: 'Finished at',
            render: function Render(_, asyncMigration: AsyncMigration): JSX.Element {
                const finishedAt = asyncMigration.finished_at
                return <div>{humanFriendlyDetailedTime(finishedAt)}</div>
            },
        },
        {
            title: '',
            render: function Render(_, asyncMigration: AsyncMigration): JSX.Element {
                const status = asyncMigration.status
                return (
                    <div>
                        {status === AsyncMigrationStatus.NotStarted ? (
                            <Tooltip title="Start">
                                <LemonButton
                                    type="stealth"
                                    icon={<PlayCircleOutlined />}
                                    onClick={() => triggerMigration(asyncMigration.id)}
                                    fullWidth
                                />
                            </Tooltip>
                        ) : status === AsyncMigrationStatus.Running ? (
                            <More
                                overlay={
                                    <>
                                        <LemonButton
                                            type="stealth"
                                            onClick={() => forceStopMigration(asyncMigration.id)}
                                            fullWidth
                                        >
                                            Stop and rollback
                                        </LemonButton>
                                        <LemonButton
                                            type="stealth"
                                            onClick={() => forceStopMigrationWithoutRollback(asyncMigration.id)}
                                            fullWidth
                                        >
                                            Stop
                                        </LemonButton>
                                    </>
                                }
                            />
                        ) : status === AsyncMigrationStatus.CompletedSuccessfully ? (
                            <></>
                        ) : status === AsyncMigrationStatus.Errored ? (
                            <More
                                overlay={
                                    <>
                                        <LemonButton
                                            type="stealth"
                                            onClick={() => resumeMigration(asyncMigration.id)}
                                            fullWidth
                                        >
                                            Resume
                                        </LemonButton>
                                        <LemonButton
                                            type="stealth"
                                            onClick={() => triggerMigration(asyncMigration.id)}
                                            fullWidth
                                        >
                                            Restart without rollback
                                        </LemonButton>
                                        <LemonButton
                                            type="stealth"
                                            onClick={() => rollbackMigration(asyncMigration.id)}
                                            fullWidth
                                        >
                                            Rollback
                                        </LemonButton>
                                    </>
                                }
                            />
                        ) : status === AsyncMigrationStatus.RolledBack ? (
                            <Tooltip title="Restart">
                                <LemonButton
                                    type="stealth"
                                    icon={<RedoOutlined />}
                                    onClick={() => triggerMigration(asyncMigration.id)}
                                    fullWidth
                                />
                            </Tooltip>
                        ) : status === AsyncMigrationStatus.Starting ? (
                            <Spinner size="sm" />
                        ) : (
                            <></>
                        )}
                    </div>
                )
            },
        },
    ]
    const rowExpansion = {
        expandedRowRender: function renderExpand(asyncMigration: AsyncMigration) {
            return asyncMigration && <AsyncMigrationDetails asyncMigration={asyncMigration} />
        },
        rowExpandable: (asyncMigration: AsyncMigration) => asyncMigration.error_count > 0,
        onRowExpand: function getErrors(asyncMigration: AsyncMigration) {
            loadAsyncMigrationErrors(asyncMigration.id)
        },
    }
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
                            <LemonTable
                                pagination={{ pageSize: 10 }}
                                loading={asyncMigrationsLoading}
                                columns={columns}
                                dataSource={asyncMigrations}
                                expandable={rowExpansion}
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
