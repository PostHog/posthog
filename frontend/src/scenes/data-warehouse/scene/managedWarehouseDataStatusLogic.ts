import { afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { dataWarehouseManagedWarehouseDataStatusRetrieve } from 'products/data_warehouse/frontend/generated/api'
import type {
    ManagedWarehouseDataStatusResponseApi,
    ManagedWarehouseReadinessStateEnumApi,
} from 'products/data_warehouse/frontend/generated/api.schemas'

import type { managedWarehouseDataStatusLogicType } from './managedWarehouseDataStatusLogicType'

const ACTIVE_REFRESH_INTERVAL_MS = 15_000
const STABLE_REFRESH_INTERVAL_MS = 60_000
const ACTIVE_STATES: ManagedWarehouseReadinessStateEnumApi[] = ['waiting', 'backfilling', 'catching_up']

export const managedWarehouseDataStatusLogic = kea<managedWarehouseDataStatusLogicType>([
    path(['scenes', 'data-warehouse', 'scene', 'managedWarehouseDataStatusLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
    })),
    loaders(({ values }) => ({
        managedWarehouseDataStatus: [
            null as ManagedWarehouseDataStatusResponseApi | null,
            {
                loadManagedWarehouseDataStatus: async () => {
                    return await dataWarehouseManagedWarehouseDataStatusRetrieve(String(values.currentTeamId))
                },
            },
        ],
    })),
    selectors({
        hasActiveWork: [
            (s) => [s.managedWarehouseDataStatus],
            (managedWarehouseDataStatus): boolean =>
                managedWarehouseDataStatus !== null &&
                ACTIVE_STATES.includes(managedWarehouseDataStatus.overall_readiness_state),
        ],
    }),
    listeners(({ actions, values, cache }) => ({
        loadManagedWarehouseDataStatusSuccess: () => {
            cache.disposables.add(() => {
                const timeoutId = window.setTimeout(
                    () => actions.loadManagedWarehouseDataStatus(),
                    values.hasActiveWork ? ACTIVE_REFRESH_INTERVAL_MS : STABLE_REFRESH_INTERVAL_MS
                )
                return () => window.clearTimeout(timeoutId)
            }, 'managedWarehouseDataStatusPoll')
        },
        loadManagedWarehouseDataStatusFailure: () => {
            cache.disposables.add(() => {
                const timeoutId = window.setTimeout(
                    () => actions.loadManagedWarehouseDataStatus(),
                    STABLE_REFRESH_INTERVAL_MS
                )
                return () => window.clearTimeout(timeoutId)
            }, 'managedWarehouseDataStatusPoll')
        },
    })),
    afterMount(({ actions }) => {
        actions.loadManagedWarehouseDataStatus()
    }),
])
