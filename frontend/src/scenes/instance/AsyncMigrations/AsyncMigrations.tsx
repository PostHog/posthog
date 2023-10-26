import { useEffect } from 'react'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { Button, Progress, Space } from 'antd'
import { useActions, useValues } from 'kea'
import { PlayCircleOutlined } from '@ant-design/icons'
import {
    AsyncMigration,
    migrationStatusNumberToMessage,
    asyncMigrationsLogic,
    AsyncMigrationsTab,
    AsyncMigrationStatus,
} from './asyncMigrationsLogic'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { userLogic } from 'scenes/userLogic'
import { SettingUpdateField } from './SettingUpdateField'
import { LemonTable, LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { AsyncMigrationDetails } from './AsyncMigrationDetails'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag/LemonTag'
import { IconRefresh, IconReplay } from 'lib/lemon-ui/icons'
import { AsyncMigrationParametersModal } from 'scenes/instance/AsyncMigrations/AsyncMigrationParametersModal'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { Link } from '@posthog/lemon-ui'

export const scene: SceneExport = {
    component: AsyncMigrations,
    logic: asyncMigrationsLogic,
}

type AsyncMigrationColumnType = LemonTableColumn<AsyncMigration, keyof AsyncMigration | undefined>

const STATUS_RELOAD_INTERVAL_MS = 3000

export function AsyncMigrations(): JSX.Element {
    const { user } = useValues(userLogic)
    const {
        asyncMigrationsLoading,
        activeTab,
        asyncMigrationSettings,
        isAnyMigrationRunning,
        activeAsyncMigrationModal,
        actionableMigrations,
        futureMigrations,
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

    useEffect(() => {
        if (isAnyMigrationRunning) {
            const interval = setInterval(() => loadAsyncMigrations(), STATUS_RELOAD_INTERVAL_MS)
            return () => clearInterval(interval)
        }
    }, [isAnyMigrationRunning])

    const nameColumn: AsyncMigrationColumnType = {
        title: 'Migration',
        render: function Render(_, asyncMigration: AsyncMigration): JSX.Element {
            const link =
                'https://github.com/PostHog/posthog/blob/master/posthog/async_migrations/migrations/' +
                asyncMigration.name +
                '.py'
            return (
                <>
                    <div className="row-name">
                        <Link to={link}>{asyncMigration.name}</Link>
                    </div>
                    <div className="row-description">{asyncMigration.description}</div>
                </>
            )
        },
    }
    const progressColumn: AsyncMigrationColumnType = {
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
    const statusColumn: AsyncMigrationColumnType = {
        title: 'Status',
        render: function Render(_, asyncMigration: AsyncMigration): JSX.Element {
            const status = asyncMigration.status
            const type: LemonTagType =
                status === AsyncMigrationStatus.Running
                    ? 'success'
                    : status === AsyncMigrationStatus.Errored || status === AsyncMigrationStatus.FailedAtStartup
                    ? 'danger'
                    : status === AsyncMigrationStatus.Starting
                    ? 'warning'
                    : status === AsyncMigrationStatus.RolledBack
                    ? 'warning'
                    : 'default'
            return (
                <LemonTag type={type} className="uppercase">
                    {migrationStatusNumberToMessage[status]}
                </LemonTag>
            )
        },
    }
    const lastOpColumn: AsyncMigrationColumnType = {
        title: 'Last operation index',
        render: function Render(_, asyncMigration: AsyncMigration): JSX.Element {
            return <div>{asyncMigration.current_operation_index}</div>
        },
    }
    const queryIdColumn: AsyncMigrationColumnType = {
        title: 'Last query ID',
        render: function Render(_, asyncMigration: AsyncMigration): JSX.Element {
            return (
                <div>
                    <small>{asyncMigration.current_query_id}</small>
                </div>
            )
        },
    }
    const startedAtColumn: AsyncMigrationColumnType = {
        title: 'Started at',
        render: function Render(_, asyncMigration: AsyncMigration): JSX.Element {
            const startedAt = asyncMigration.started_at
            return <div>{humanFriendlyDetailedTime(startedAt)}</div>
        },
    }
    const finishedAtColumn: AsyncMigrationColumnType = {
        title: 'Finished at',
        render: function Render(_, asyncMigration: AsyncMigration): JSX.Element {
            const finishedAt = asyncMigration.finished_at
            return <div>{humanFriendlyDetailedTime(finishedAt)}</div>
        },
    }
    const ActionsColumn: AsyncMigrationColumnType = {
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

    const minVersionColumn: AsyncMigrationColumnType = {
        title: 'Minimum PostHog version',
        render: function Render(_, asyncMigration: AsyncMigration): JSX.Element {
            return <div>{asyncMigration.posthog_min_version}</div>
        },
    }
    const maxVersionColumn: AsyncMigrationColumnType = {
        title: 'Maximum PostHog version',
        render: function Render(_, asyncMigration: AsyncMigration): JSX.Element {
            return <div>{asyncMigration.posthog_max_version}</div>
        },
    }

    const columns = {}
    columns[AsyncMigrationsTab.FutureMigrations] = [nameColumn, statusColumn, minVersionColumn, maxVersionColumn]
    columns[AsyncMigrationsTab.Management] = [
        nameColumn,
        progressColumn,
        statusColumn,
        lastOpColumn,
        queryIdColumn,
        startedAtColumn,
        finishedAtColumn,
        ActionsColumn,
    ]
    const migrations = {}
    migrations[AsyncMigrationsTab.FutureMigrations] = futureMigrations
    migrations[AsyncMigrationsTab.Management] = actionableMigrations

    const rowExpansion = {
        expandedRowRender: function renderExpand(asyncMigration: AsyncMigration) {
            return asyncMigration && <AsyncMigrationDetails asyncMigration={asyncMigration} />
        },
        rowExpandable: (asyncMigration: AsyncMigration) => asyncMigration.error_count > 0,
        onRowExpand: function getErrors(asyncMigration: AsyncMigration) {
            loadAsyncMigrationErrors(asyncMigration.id)
        },
    }

    const tabs = [
        {
            key: AsyncMigrationsTab.Management,
            label: `Management (${actionableMigrations.length})`,
        },
        {
            key: AsyncMigrationsTab.Settings,
            label: 'Settings',
        },
    ]

    if (futureMigrations.length > 0) {
        tabs.splice(1, 0, {
            key: AsyncMigrationsTab.FutureMigrations,
            label: `Future Migrations (${futureMigrations.length})`,
        })
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
                                    <Link to="https://posthog.com/docs/self-host/configure/async-migrations/overview">
                                        dedicated docs page
                                    </Link>
                                    .
                                </p>
                            </>
                        }
                    />

                    <LemonTabs activeKey={activeTab} onChange={setActiveTab} tabs={tabs} />

                    {[AsyncMigrationsTab.Management, AsyncMigrationsTab.FutureMigrations].includes(activeTab) ? (
                        <>
                            <div className="mb-4 float-right">
                                <LemonButton
                                    icon={asyncMigrationsLoading ? <Spinner /> : <IconRefresh />}
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
                                columns={columns[activeTab]}
                                dataSource={migrations[activeTab]}
                                expandable={rowExpansion}
                            />
                            {activeAsyncMigrationModal ? (
                                <AsyncMigrationParametersModal {...activeAsyncMigrationModal} />
                            ) : null}
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
