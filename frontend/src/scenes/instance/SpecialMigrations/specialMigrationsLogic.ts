import { successToast } from 'lib/utils'
import api from 'lib/api'
import { kea } from 'kea'
import { userLogic } from 'scenes/userLogic'

import { specialMigrationsLogicType } from './specialMigrationsLogicType'
export type TabName = 'overview' | 'internal_metrics'

export enum SpecialMigrationStatus {
    NotStarted = 0,
    Running = 1,
    CompletedSuccessfully = 2,
    Errored = 3,
    RolledBack = 4,
}
export interface SpecialMigration {
    id: number
    name: string
    progress: number
    status: SpecialMigrationStatus
    current_operation_index: number
    current_query_id: string
    celery_task_id: string
    started_at: string
    finished_at: string
    error: string
}

export const specialMigrationsLogic = kea<specialMigrationsLogicType<SpecialMigration>>({
    path: ['scenes', 'instance', 'SpecialMigrations', 'specialMigrationsLogic'],
    actions: {
        triggerMigration: (migrationId: number) => ({ migrationId }),
        forceStopMigration: (migrationId: number) => ({ migrationId }),
    },
    loaders: () => ({
        specialMigrations: [
            null as SpecialMigration[] | null,
            {
                loadSpecialMigrations: async () => {
                    if (!userLogic.values.user?.is_staff) {
                        return null
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
                successToast('Failed to trigger migration', res.error)
            }
        },
        forceStopMigration: async ({ migrationId }) => {
            const res = await api.create(`/api/special_migrations/${migrationId}/force_stop`)
            if (res.success) {
                successToast('Force stop triggered successfully')
                actions.loadSpecialMigrations()
            } else {
                successToast('Failed to trigger force stop', res.error)
            }
        },
    }),

    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadSpecialMigrations()
        },
    }),
})
