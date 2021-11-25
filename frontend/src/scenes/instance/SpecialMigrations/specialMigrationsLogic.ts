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

    listeners: () => ({
        triggerMigration: async ({ migrationId }) => {
            const res = await api.create(`/api/special_migration/${migrationId}/trigger`)
            const resJson = await res.json()
            if (resJson.success) {
                successToast('Migration triggered successfully')
            } else {
                successToast('Failed to trigger migration', resJson.error)
            }
        },
        forceStopMigration: async ({ migrationId }) => {
            const res = await api.create(`/api/special_migration/${migrationId}/force_stop`)
            const resJson = await res.json()
            if (resJson.success) {
                successToast('Force stop triggered successfully')
            } else {
                successToast('Failed to trigger force stop', resJson.error)
            }
        },
    }),

    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadSpecialMigrations()
        },
    }),
})
