import { errorToast, successToast } from 'lib/utils'
import api from 'lib/api'
import { kea } from 'kea'
import { userLogic } from 'scenes/userLogic'

import { specialMigrationsLogicType } from './specialMigrationsLogicType'
export type TabName = 'overview' | 'internal_metrics'

// keep in sync with MigrationStatus in posthog/models/special_migration.py
export enum SpecialMigrationStatus {
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
export interface SpecialMigration {
    id: number
    name: string
    description: string
    progress: number
    status: SpecialMigrationStatus
    current_operation_index: number
    current_query_id: string
    celery_task_id: string
    started_at: string
    finished_at: string
    last_error: string
    posthog_min_version: string
    posthog_max_version: string
}

export const specialMigrationsLogic = kea<specialMigrationsLogicType<SpecialMigration>>({
    path: ['scenes', 'instance', 'SpecialMigrations', 'specialMigrationsLogic'],
    actions: {
        triggerMigration: (migrationId: number) => ({ migrationId }),
        forceStopMigration: (migrationId: number) => ({ migrationId }),
    },
    loaders: () => ({
        specialMigrations: [
            [] as SpecialMigration[],
            {
                loadSpecialMigrations: async () => {
                    if (!userLogic.values.user?.is_staff) {
                        return []
                    }
                    return (await api.get('api/special_migrations')).results
                },
            },
        ],
    }),

    listeners: ({ actions }) => ({
        triggerMigration: async ({ migrationId }) => {
            const res = await api.create(`/api/special_migrations/${migrationId}/trigger`)
            if (res.success) {
                successToast('Migration triggered successfully')
                actions.loadSpecialMigrations()
            } else {
                errorToast('Failed to trigger migration', res.error)
            }
        },
        forceStopMigration: async ({ migrationId }) => {
            const res = await api.create(`/api/special_migrations/${migrationId}/force_stop`)
            if (res.success) {
                successToast('Force stop triggered successfully')
                actions.loadSpecialMigrations()
            } else {
                errorToast('Failed to trigger force stop', res.error)
            }
        },
    }),

    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadSpecialMigrations()
        },
    }),
})
