import { errorToast, successToast } from 'lib/utils'
import api from 'lib/api'
import { kea } from 'kea'
import { userLogic } from 'scenes/userLogic'

import { asyncMigrationsLogicType } from './asyncMigrationsLogicType'
import { InstanceSetting } from '~/types'
export type TabName = 'overview' | 'internal_metrics'

// keep in sync with MigrationStatus in posthog/models/async_migration.py
export enum AsyncMigrationStatus {
    NotStarted = 0,
    Running = 1,
    CompletedSuccessfully = 2,
    Errored = 3,
    RolledBack = 4,
    Starting = 5,
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

export const asyncMigrationsLogic = kea<
    asyncMigrationsLogicType<AsyncMigration, AsyncMigrationError, AsyncMigrationsTab>
>({
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
        activeTab: [AsyncMigrationsTab.Management, { setActiveTab: (_, { tab }) => tab }],
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

    listeners: ({ actions }) => ({
        triggerMigration: async ({ migrationId }) => {
            const res = await api.create(`/api/async_migrations/${migrationId}/trigger`)
            if (res.success) {
                successToast('Migration triggered successfully')
                actions.loadAsyncMigrations()
            } else {
                errorToast('Failed to trigger migration', res.error)
            }
        },
        resumeMigration: async ({ migrationId }) => {
            const res = await api.create(`/api/async_migrations/${migrationId}/resume`)
            if (res.success) {
                successToast('Migration resume triggered successfully')
                actions.loadAsyncMigrations()
            } else {
                errorToast('Failed to resume migration', res.error)
            }
        },
        rollbackMigration: async ({ migrationId }) => {
            const res = await api.create(`/api/async_migrations/${migrationId}/rollback`)
            if (res.success) {
                successToast('Migration rolledback triggered successfully')
                actions.loadAsyncMigrations()
            } else {
                errorToast('Failed to rollback migration', res.error)
            }
        },
        forceStopMigration: async ({ migrationId }) => {
            const res = await api.create(`/api/async_migrations/${migrationId}/force_stop`)
            if (res.success) {
                successToast('Force stop triggered successfully')
                actions.loadAsyncMigrations()
            } else {
                errorToast('Failed to trigger force stop', res.error)
            }
        },
        forceStopMigrationWithoutRollback: async ({ migrationId }) => {
            const res = await api.create(`/api/async_migrations/${migrationId}/force_stop_without_rollback`)
            if (res.success) {
                successToast('Force stop without rollback triggered successfully')
                actions.loadAsyncMigrations()
            } else {
                errorToast('Failed to trigger force stop without rollback', res.error)
            }
        },
        updateSetting: async ({ settingKey, newValue }) => {
            try {
                await api.update(`/api/instance_settings/${settingKey}`, {
                    value: newValue,
                })
                successToast('Setting updated successfully!', `Instance setting ${settingKey} has been updated.`)
                actions.loadAsyncMigrationSettings()
            } catch {
                errorToast('Failed to trigger migration.', 'Please try again or contact support.')
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
