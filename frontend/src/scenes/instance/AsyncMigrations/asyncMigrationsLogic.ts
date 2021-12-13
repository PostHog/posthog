import { errorToast, successToast } from 'lib/utils'
import api from 'lib/api'
import { kea } from 'kea'
import { userLogic } from 'scenes/userLogic'

import { asyncMigrationsLogicType } from './asyncMigrationsLogicType'
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

export const migrationStatusNumberToMessage = {
    0: 'Not started',
    1: 'Running',
    2: 'Completed successfully',
    3: 'Errored',
    4: 'Rolled back',
    5: 'Starting',
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
    last_error: string
    posthog_min_version: string
    posthog_max_version: string
}

export const asyncMigrationsLogic = kea<asyncMigrationsLogicType<AsyncMigration>>({
    path: ['scenes', 'instance', 'AsyncMigrations', 'asyncMigrationsLogic'],
    actions: {
        triggerMigration: (migrationId: number) => ({ migrationId }),
        forceStopMigration: (migrationId: number) => ({ migrationId }),
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
        forceStopMigration: async ({ migrationId }) => {
            const res = await api.create(`/api/async_migrations/${migrationId}/force_stop`)
            if (res.success) {
                successToast('Force stop triggered successfully')
                actions.loadAsyncMigrations()
            } else {
                errorToast('Failed to trigger force stop', res.error)
            }
        },
    }),

    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadAsyncMigrations()
        },
    }),
})
