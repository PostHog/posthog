import React, { useEffect } from 'react'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { Button, Progress, Space, Tabs } from 'antd'
import { useActions, useValues } from 'kea'
import { PlayCircleOutlined } from '@ant-design/icons'
import {
    AsyncMigration,
    migrationStatusNumberToMessage,
    asyncMigrationsLogic,
    AsyncMigrationsTab,
    AsyncMigrationStatus,
} from './asyncMigrationsLogic'
import { Tooltip } from 'lib/components/Tooltip'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { userLogic } from 'scenes/userLogic'
import { SettingUpdateField } from './SettingUpdateField'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { AsyncMigrationDetails } from './AsyncMigrationDetails'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { More } from 'lib/components/LemonButton/More'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonTag, LemonTagPropsType } from 'lib/components/LemonTag/LemonTag'
import { IconRefresh, IconReplay } from 'lib/components/icons'
import { AsyncMigrationParametersModal } from 'scenes/instance/AsyncMigrations/AsyncMigrationParametersModal'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

const { TabPane } = Tabs

export const scene: SceneExport = {
    component: AsyncMigrations,
    logic: asyncMigrationsLogic,
}

const STATUS_RELOAD_INTERVAL_MS = 3000

export function AsyncMigrations(): JSX.Element {
    const { user } = useValues(userLogic)
    const {
        asyncMigrations,
        asyncMigrationsLoading,
        activeTab,
        asyncMigrationSettings,
        isAnyMigrationRunning,
        activeAsyncMigrationModal,
    } = useValues(asyncMigrationsLogic)
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
    const { preflight } = useValues(preflightLogic)

    useEffect(() => {
        if (isAnyMigrationRunning) {
            const interval = setInterval(() => loadAsyncMigrations(), STATUS_RELOAD_INTERVAL_MS)
            return () => clearInterval(interval)
        }
    }, [isAnyMigrationRunning])

    const nameColumn = {
        title: 'Migration',
        render: function Render(_, asyncMigration: AsyncMigration): JSX.Element {
            const link =
                'https://github.com/PostHog/posthog/blob/master/posthog/async_migrations/migrations/' +
                asyncMigration.name +
                '.py'
            return (
                <>
                    <div className="row-name">
                        <a href={link}>{asyncMigration.name}</a>
                    </div>
                    <div className="row-description">{asyncMigration.description}</div>
                </>
            )
        },
    }
    const progressColumn = {
        title: 'Progress',
        render: function Render(_, asyncMigration: AsyncMigration): JSX.Element {
            const progress = asyncMigration.progress
            return (
                <div>
                    <Progress percent={progress} />
                </div>
            )
        },
    }
    const statusColumn = {
        title: 'Status',
        render: function Render(_, asyncMigration: AsyncMigration): JSX.Element {
            const status = asyncMigration.status
            const type: LemonTagPropsType =
                status === AsyncMigrationStatus.Running
                    ? 'success'
                    : status === AsyncMigrationStatus.Errored || status === AsyncMigrationStatus.FailedAtStartup
                    ? 'danger'
                    : status === AsyncMigrationStatus.Starting
                    ? 'warning'
                    : status === AsyncMigrationStatus.RolledBack
                    ? 'warning'
                    : 'default'
            return <LemonTag type={type}>{migrationStatusNumberToMessage[status]}</LemonTag>
        },
    }
    const lastOpColumn = {
        title: 'Last operation index',
        render: function Render(_, asyncMigration: AsyncMigration): JSX.Element {
            return <div>{asyncMigration.current_operation_index}</div>
        },
    }
    const queryIdColumn = {
        title: 'Last query ID',
        render: function Render(_, asyncMigration: AsyncMigration): JSX.Element {
            return (
                <div>
                    <small>{asyncMigration.current_query_id}</small>
                </div>
            )
        },
    }
    const startedAtColumn = {
        title: 'Started at',
        render: function Render(_, asyncMigration: AsyncMigration): JSX.Element {
            const startedAt = asyncMigration.started_at
            return <div>{humanFriendlyDetailedTime(startedAt)}</div>
        },
    }
    const finishedAtColumn = {
        title: 'Finished at',
        render: function Render(_, asyncMigration: AsyncMigration): JSX.Element {
            const finishedAt = asyncMigration.finished_at
            return <div>{humanFriendlyDetailedTime(finishedAt)}</div>
        },
    }
    const ActionsColumn = {
        title: '',
        render: function Render(_, asyncMigration: AsyncMigration): JSX.Element {
            const status = asyncMigration.status
            return (
                <div>
                    {status === AsyncMigrationStatus.NotStarted || status === AsyncMigrationStatus.FailedAtStartup ? (
                        <Tooltip title="Start">
                            <Button
                                type="link"
                                icon={<PlayCircleOutlined />}
                                onClick={() => triggerMigration(asyncMigration)}
                            >
                                Run
                            </Button>
                        </Tooltip>
                    ) : status === AsyncMigrationStatus.Starting || status === AsyncMigrationStatus.Running ? (
                        <More
                            overlay={
                                <>
                                    <LemonButton
                                        status="stealth"
                                        onClick={() => forceStopMigration(asyncMigration)}
                                        fullWidth
                                    >
                                        Stop and rollback
                                    </LemonButton>
                                    <LemonButton
                                        status="stealth"
                                        onClick={() => forceStopMigrationWithoutRollback(asyncMigration)}
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
                                        status="stealth"
                                        onClick={() => resumeMigration(asyncMigration)}
                                        fullWidth
                                    >
                                        Resume
                                    </LemonButton>
                                    <LemonButton
                                        status="stealth"
                                        onClick={() => rollbackMigration(asyncMigration)}
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
                                status="stealth"
                                icon={<IconReplay />}
                                onClick={() => triggerMigration(asyncMigration)}
                                fullWidth
                            />
                        </Tooltip>
                    ) : null}
                </div>
            )
        },
    }

    const minVersionColumn = {
        title: 'Min PostHog Version',
        render: function Render(_, asyncMigration: AsyncMigration): JSX.Element {
            return <div>{asyncMigration.posthog_min_version}</div>
        },
    }
    const maxVersionColumn = {
        title: 'Max PostHog Version',
        render: function Render(_, asyncMigration: AsyncMigration): JSX.Element {
            return <div>{asyncMigration.posthog_max_version}</div>
        },
    }

    const availableMigrationsColumns: LemonTableColumns<AsyncMigration> = [
        nameColumn,
        progressColumn,
        statusColumn,
        lastOpColumn,
        queryIdColumn,
        startedAtColumn,
        finishedAtColumn,
        ActionsColumn,
    ]
    const futureMigrationsColumns: LemonTableColumns<AsyncMigration> = [
        nameColumn,
        statusColumn,
        minVersionColumn,
        maxVersionColumn,
    ]
    const completedMigrationsColumns: LemonTableColumns<AsyncMigration> = [
        nameColumn,
        startedAtColumn,
        finishedAtColumn,
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
        <div>
            {user?.is_staff ? (
                <>
                    <PageHeader
                        title="Async Migrations"
                        caption={
                            <>
                                <p>Manage async migrations in your instance.</p>
                                <p>
                                    Read about async migrations on our{' '}
                                    <a href="https://posthog.com/docs/self-host/configure/async-migrations/overview">
                                        dedicated docs page
                                    </a>
                                    .
                                </p>
                            </>
                        }
                    />

                    <Tabs activeKey={activeTab} onChange={(t) => setActiveTab(t as AsyncMigrationsTab)}>
                        <TabPane tab="Management" key={AsyncMigrationsTab.Management} />
                        <TabPane tab="Future Migrations" key={AsyncMigrationsTab.FutureMigrations} />
                        <TabPane tab="Completed Migrations" key={AsyncMigrationsTab.CompletedMigrations} />
                        <TabPane tab="Settings" key={AsyncMigrationsTab.Settings} />
                    </Tabs>

                    {activeTab === AsyncMigrationsTab.Management ? (
                        <>
                            <div className="mb-4 float-right">
                                <LemonButton
                                    icon={asyncMigrationsLoading ? <Spinner size="sm" /> : <IconRefresh />}
                                    onClick={loadAsyncMigrations}
                                    type="secondary"
                                    size="small"
                                >
                                    Refresh
                                </LemonButton>
                            </div>
                            <Space />
                            <LemonTable
                                pagination={{ pageSize: 10 }}
                                loading={asyncMigrationsLoading}
                                columns={availableMigrationsColumns}
                                dataSource={asyncMigrations} // TODO: filter out migrations based on version & completed
                                expandable={rowExpansion}
                            />
                            {activeAsyncMigrationModal ? (
                                <AsyncMigrationParametersModal {...activeAsyncMigrationModal} />
                            ) : null}
                        </>
                    ) : activeTab === AsyncMigrationsTab.FutureMigrations ? (
                        <>
                            <div className="mb-4 float-right">
                                <LemonButton
                                    icon={asyncMigrationsLoading ? <Spinner size="sm" /> : <IconRefresh />}
                                    onClick={loadAsyncMigrations}
                                    type="secondary"
                                    size="small"
                                >
                                    Refresh
                                </LemonButton>
                            </div>
                            <div>
                                These migrations are not available on your current PostHog version (
                                {preflight?.posthog_version}).
                            </div>
                            <Space />
                            <LemonTable
                                pagination={{ pageSize: 10 }}
                                loading={asyncMigrationsLoading}
                                columns={futureMigrationsColumns}
                                dataSource={asyncMigrations} // TODO: filter out migrations based on version & completed
                                expandable={rowExpansion}
                            />
                        </>
                    ) : activeTab === AsyncMigrationsTab.CompletedMigrations ? (
                        <>
                            <div className="mb-4 float-right">
                                <LemonButton
                                    icon={asyncMigrationsLoading ? <Spinner size="sm" /> : <IconRefresh />}
                                    onClick={loadAsyncMigrations}
                                    type="secondary"
                                    size="small"
                                >
                                    Refresh
                                </LemonButton>
                            </div>
                            <Space />
                            <LemonTable
                                pagination={{ pageSize: 10 }}
                                loading={asyncMigrationsLoading}
                                columns={completedMigrationsColumns}
                                dataSource={asyncMigrations} // TODO: filter out migrations based on completed
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
