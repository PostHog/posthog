import api from 'lib/api'
import { kea } from 'kea'
import { userLogic } from 'scenes/userLogic'

import type { asyncMigrationsLogicType } from './asyncMigrationsLogicType'
import { systemStatusLogic } from 'scenes/instance/SystemStatus/systemStatusLogic'
import { InstanceSetting } from '~/types'
import { lemonToast } from 'lib/components/lemonToast'
export type TabName = 'overview' | 'internal_metrics'

// keep in sync with MigrationStatus in posthog/models/async_migration.py
export enum AsyncMigrationStatus {
    NotStarted = 0,
    Running = 1,
    CompletedSuccessfully = 2,
    Errored = 3,
    RolledBack = 4,
    Starting = 5,
    FailedAtStartup = 6,
}

export enum AsyncMigrationsTab {
    Management = 'management',
    Settings = 'settings',
}

export const migrationStatusNumberToMessage = {
    0: 'Not started',
    1: 'Running',
    2: 'Complete',
    3: 'Error',
    4: 'Rolled back',
    5: 'Starting',
    6: 'Failed at startup',
}

export interface AsyncMigrationError {
    id: number
    description: string
    created_at: string
}
export interface AsyncMigration {
    id: number
    name: string
    description: string
    progress: number
    status: AsyncMigrationStatus
    current_operation_index: number
    current_query_id: string
    celery_task_id: string
    started_at: string
    finished_at: string
    posthog_min_version: string
    posthog_max_version: string
    error_count: number
}

export const asyncMigrationsLogic = kea<asyncMigrationsLogicType>({
    path: ['scenes', 'instance', 'AsyncMigrations', 'asyncMigrationsLogic'],
    actions: {
        triggerMigration: (migrationId: number) => ({ migrationId }),
        resumeMigration: (migrationId: number) => ({ migrationId }),
        rollbackMigration: (migrationId: number) => ({ migrationId }),
        forceStopMigration: (migrationId: number) => ({ migrationId }),
        forceStopMigrationWithoutRollback: (migrationId: number) => ({ migrationId }),
        setActiveTab: (tab: AsyncMigrationsTab) => ({ tab }),
        updateSetting: (settingKey: string, newValue: string) => ({ settingKey, newValue }),
        loadAsyncMigrationErrors: (migrationId: number) => ({ migrationId }),
        loadAsyncMigrationErrorsSuccess: (migrationId: number, errors: AsyncMigrationError[]) => ({
            migrationId,
            errors,
        }),
        loadAsyncMigrationErrorsFailure: (migrationId: number, error: any) => ({ migrationId, error }),
    },

    reducers: {
        activeTab: [AsyncMigrationsTab.Management as AsyncMigrationsTab, { setActiveTab: (_, { tab }) => tab }],
        asyncMigrationErrors: [
            {} as Record<number, AsyncMigrationError[]>,
            {
                loadAsyncMigrationErrorsSuccess: (state, { migrationId, errors }) => {
                    return { ...state, [migrationId]: errors }
                },
            },
        ],
        asyncMigrationErrorsLoading: [
            {} as Record<number, boolean>,
            {
                loadAsyncMigrationErrors: (state, { migrationId }) => {
                    return { ...state, [migrationId]: true }
                },
                loadAsyncMigrationErrorsSuccess: (state, { migrationId }) => {
                    return { ...state, [migrationId]: false }
                },
                loadAsyncMigrationErrorsFailure: (state, { migrationId }) => {
                    return { ...state, [migrationId]: false }
                },
            },
        ],
    },
    loaders: () => ({
        asyncMigrations: [
            [] as AsyncMigration[],
            {
                loadAsyncMigrations: async () => {
                    if (!userLogic.values.user?.is_staff) {
                        return []
                    }
                    return (await api.get('api/async_migrations')).results
                },
            },
        ],
        asyncMigrationSettings: [
            [] as InstanceSetting[],
            {
                loadAsyncMigrationSettings: async (): Promise<InstanceSetting[]> => {
                    if (!userLogic.values.user?.is_staff) {
                        return []
                    }
                    const settings: InstanceSetting[] = (await api.get('api/instance_settings')).results
                    return settings.filter((setting) => setting.key.includes('ASYNC_MIGRATIONS'))
                },
            },
        ],
    }),

    selectors: {
        isAnyMigrationRunning: [
            (s) => [s.asyncMigrations],
            (asyncMigrations) =>
                asyncMigrations.some((migration) =>
                    [AsyncMigrationStatus.Running, AsyncMigrationStatus.Starting].includes(migration.status)
                ),
        ],
    },

    listeners: ({ actions }) => ({
        triggerMigration: async ({ migrationId }) => {
            const res = await api.create(`/api/async_migrations/${migrationId}/trigger`)
            if (res.success) {
                lemonToast.success('Migration triggered successfully')
                actions.loadAsyncMigrations()
            } else {
                lemonToast.error(res.error)
            }
        },
        resumeMigration: async ({ migrationId }) => {
            const res = await api.create(`/api/async_migrations/${migrationId}/resume`)
            if (res.success) {
                lemonToast.success('Migration resume triggered successfully')
                actions.loadAsyncMigrations()
            } else {
                lemonToast.error(res.error)
            }
        },
        rollbackMigration: async ({ migrationId }) => {
            const res = await api.create(`/api/async_migrations/${migrationId}/rollback`)
            if (res.success) {
                lemonToast.success('Migration rolledback triggered successfully')
                actions.loadAsyncMigrations()
            } else {
                lemonToast.error(res.error)
            }
        },
        forceStopMigration: async ({ migrationId }) => {
            const res = await api.create(`/api/async_migrations/${migrationId}/force_stop`)
            if (res.success) {
                lemonToast.success('Force stop triggered successfully')
                actions.loadAsyncMigrations()
            } else {
                lemonToast.error(res.error)
            }
        },
        forceStopMigrationWithoutRollback: async ({ migrationId }) => {
            const res = await api.create(`/api/async_migrations/${migrationId}/force_stop_without_rollback`)
            if (res.success) {
                lemonToast.success('Force stop without rollback triggered successfully')
                actions.loadAsyncMigrations()
            } else {
                lemonToast.error(res.error)
            }
        },
        updateSetting: async ({ settingKey, newValue }) => {
            // TODO: Use systemStatusLogic.ts for consistency
            try {
                await api.update(`/api/instance_settings/${settingKey}`, {
                    value: newValue,
                })
                lemonToast.success(`Instance setting ${settingKey} updated`)
                actions.loadAsyncMigrationSettings()
                actions.loadAsyncMigrations()
                systemStatusLogic.actions.loadSystemStatus()
            } catch {
                lemonToast.error('Failed to trigger migration')
            }
        },
        loadAsyncMigrationErrors: async ({ migrationId }) => {
            try {
                const errorsForMigration = await api.get(`api/async_migrations/${migrationId}/errors`)
                actions.loadAsyncMigrationErrorsSuccess(migrationId, errorsForMigration)
            } catch (error) {
                actions.loadAsyncMigrationErrorsFailure(migrationId, error)
            }
        },
    }),

    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadAsyncMigrations()
            actions.loadAsyncMigrationSettings()
        },
    }),
})
