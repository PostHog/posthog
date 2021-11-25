import { successToast } from 'lib/utils'
import api from 'lib/api'
import { kea } from 'kea'
import { userLogic } from 'scenes/userLogic'

import { specialMigrationsLogicType } from './specialMigrationsLogicType'
export type TabName = 'overview' | 'internal_metrics'

export const specialMigrationsLogic = kea<specialMigrationsLogicType>({
    path: ['scenes', 'instance', 'SpecialMigrations', 'specialMigrationsLogic'],
    actions: {
        triggerMigration: (migrationId: number) => ({ migrationId }),
        forceStopMigration: (migrationId: number) => ({ migrationId }),
    },
    loaders: () => ({
        specialMigrations: [
            null as any[] | null,
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
            const res = await api.create(`/api/special_migration/${migrationId}/trigger`)
            if (res.success) {
                successToast('Migration triggered successfully')
                actions.loadSpecialMigrations()
            } else {
                successToast('Failed to trigger migration', res.error)
            }
        },
        forceStopMigration: async ({ migrationId }) => {
            const res = await api.create(`/api/special_migration/${migrationId}/force_stop`)
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
