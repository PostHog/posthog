import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import {
    dataWarehouseCheckDatabaseNameRetrieve,
    dataWarehouseDeprovisionCreate,
    dataWarehouseProvisionCreate,
    dataWarehouseResetPasswordCreate,
    dataWarehouseWarehouseStatusRetrieve,
} from 'products/data_warehouse/frontend/generated/api'
import type { WarehouseStatusResponseApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import type { warehouseProvisioningLogicType } from './warehouseProvisioningLogicType'

export const MANAGED_WAREHOUSE_DATABASE_NAME_REGEX = /^[a-z](?:[a-z0-9-]{1,61}[a-z0-9])$/

export function isValidManagedWarehouseDatabaseName(name: string): boolean {
    return MANAGED_WAREHOUSE_DATABASE_NAME_REGEX.test(name)
}

const databaseNameStorageKey = (teamId: number | null): string =>
    `warehouse-provisioning-database-name-${teamId ?? 'unknown'}`

const currentProjectId = (): string => {
    const teamId = teamLogic.values.currentTeamId
    if (!teamId) {
        throw new Error('Current project is unavailable')
    }
    return String(teamId)
}

export const warehouseProvisioningLogic = kea<warehouseProvisioningLogicType>([
    path(['scenes', 'data-warehouse', 'scene', 'warehouseProvisioningLogic']),

    actions({
        provisionWarehouse: (params: { databaseName: string }) => params,
        provisionWarehouseComplete: true,
        deprovisionWarehouse: true,
        deprovisionWarehouseComplete: true,
        resetPassword: true,
        resetPasswordComplete: true,
        setInitialPassword: (password: string) => ({ password }),
        clearInitialPassword: true,
        pollStatus: true,
        stopPolling: true,
        setDatabaseName: (name: string) => ({ name }),
        setLastRequestedDatabaseName: (name: string | null) => ({ name }),
        checkDatabaseName: (name: string) => ({ name }),
        setDatabaseNameAvailable: (available: boolean | null) => ({ available }),
        setDatabaseNameChecking: (checking: boolean) => ({ checking }),
    }),

    loaders({
        warehouseStatus: [
            null as WarehouseStatusResponseApi | null,
            {
                loadWarehouseStatus: async () => {
                    try {
                        return await dataWarehouseWarehouseStatusRetrieve(currentProjectId())
                    } catch (e: any) {
                        if (e.status === 404) {
                            return null
                        }
                        throw e
                    }
                },
            },
        ],
    }),

    reducers({
        isProvisioning: [
            false,
            {
                provisionWarehouse: () => true,
                provisionWarehouseComplete: () => false,
            },
        ],
        isDeprovisioning: [
            false,
            {
                deprovisionWarehouse: () => true,
                deprovisionWarehouseComplete: () => false,
            },
        ],
        pollingActive: [
            false,
            {
                pollStatus: () => true,
                stopPolling: () => false,
            },
        ],
        databaseName: [
            '',
            {
                setDatabaseName: (_, { name }) => name,
                setLastRequestedDatabaseName: (state, { name }) => name ?? state,
            },
        ],
        lastRequestedDatabaseName: [
            null as string | null,
            {
                setLastRequestedDatabaseName: (_, { name }) => name,
                deprovisionWarehouse: () => null,
            },
        ],
        databaseNameAvailable: [
            null as boolean | null,
            {
                setDatabaseNameAvailable: (_, { available }) => available,
                setDatabaseName: () => null,
            },
        ],
        databaseNameChecking: [
            false,
            {
                setDatabaseNameChecking: (_, { checking }) => checking,
                setDatabaseName: () => false,
            },
        ],
        initialPassword: [
            null as string | null,
            {
                setInitialPassword: (_, { password }) => password,
                clearInitialPassword: () => null,
                deprovisionWarehouse: () => null,
            },
        ],
        isResettingPassword: [
            false,
            {
                resetPassword: () => true,
                resetPasswordComplete: () => false,
            },
        ],
    }),

    selectors({
        isActionable: [
            (s) => [s.warehouseStatus],
            (status): boolean => {
                if (!status) {
                    return true
                }
                return status.state === 'ready' || status.state === 'failed' || status.state === 'deleted'
            },
        ],
        isInProgress: [
            (s) => [s.warehouseStatus],
            (status): boolean => {
                if (!status) {
                    return false
                }
                return status.state === 'pending' || status.state === 'provisioning' || status.state === 'deleting'
            },
        ],
        isValidDatabaseName: [(s) => [s.databaseName], (name): boolean => isValidManagedWarehouseDatabaseName(name)],
        retryDatabaseName: [
            (s) => [s.databaseName, s.lastRequestedDatabaseName],
            (databaseName, lastRequestedDatabaseName): string => databaseName || lastRequestedDatabaseName || '',
        ],
        canProvision: [
            (s) => [s.isValidDatabaseName, s.databaseNameAvailable],
            (valid, available): boolean => valid && available === true,
        ],
    }),

    listeners(({ actions, values }) => {
        let debounceTimer: ReturnType<typeof setTimeout> | null = null

        return {
            setDatabaseName: ({ name }) => {
                if (debounceTimer) {
                    clearTimeout(debounceTimer)
                }
                if (isValidManagedWarehouseDatabaseName(name)) {
                    actions.setDatabaseNameChecking(true)
                    debounceTimer = setTimeout(() => {
                        actions.checkDatabaseName(name)
                    }, 400)
                }
            },

            checkDatabaseName: async ({ name }) => {
                try {
                    const result = await dataWarehouseCheckDatabaseNameRetrieve(currentProjectId(), { name })
                    if (values.databaseName === name) {
                        actions.setDatabaseNameAvailable(result.available)
                    }
                } catch {
                    actions.setDatabaseNameAvailable(null)
                }
                actions.setDatabaseNameChecking(false)
            },

            provisionWarehouse: async ({ databaseName }) => {
                actions.setLastRequestedDatabaseName(databaseName)
                window.localStorage.setItem(databaseNameStorageKey(teamLogic.values.currentTeamId), databaseName)
                try {
                    const result = await dataWarehouseProvisionCreate(currentProjectId(), {
                        database_name: databaseName,
                    })
                    if (result.password) {
                        actions.setInitialPassword(result.password)
                    }
                    lemonToast.success('Warehouse provisioning started')
                    actions.loadWarehouseStatus()
                    actions.pollStatus()
                } catch (e: any) {
                    lemonToast.error(`Failed to provision warehouse: ${e.message || 'Unknown error'}`)
                }
                actions.provisionWarehouseComplete()
            },

            resetPassword: async () => {
                try {
                    const result = await dataWarehouseResetPasswordCreate(currentProjectId())
                    if (result.password) {
                        actions.setInitialPassword(result.password)
                    }
                    lemonToast.success('Password has been reset')
                } catch (e: any) {
                    lemonToast.error(`Failed to reset password: ${e.message || 'Unknown error'}`)
                }
                actions.resetPasswordComplete()
            },

            deprovisionWarehouse: async () => {
                window.localStorage.removeItem(databaseNameStorageKey(teamLogic.values.currentTeamId))
                try {
                    await dataWarehouseDeprovisionCreate(currentProjectId())
                    lemonToast.success('Warehouse deprovisioning started')
                    actions.loadWarehouseStatus()
                    actions.pollStatus()
                } catch (e: any) {
                    lemonToast.error(`Failed to deprovision warehouse: ${e.message || 'Unknown error'}`)
                }
                actions.deprovisionWarehouseComplete()
            },

            pollStatus: async (_, breakpoint) => {
                await breakpoint(10000)
                if (!values.pollingActive) {
                    return
                }
                actions.loadWarehouseStatus()
            },

            loadWarehouseStatusSuccess: ({ warehouseStatus }) => {
                if (warehouseStatus?.state === 'deleted') {
                    actions.setLastRequestedDatabaseName(null)
                    window.localStorage.removeItem(databaseNameStorageKey(teamLogic.values.currentTeamId))
                }
                if (
                    warehouseStatus &&
                    (warehouseStatus.state === 'pending' ||
                        warehouseStatus.state === 'provisioning' ||
                        warehouseStatus.state === 'deleting')
                ) {
                    actions.pollStatus()
                } else {
                    actions.stopPolling()
                }
            },
        }
    }),

    afterMount(({ actions }) => {
        const persistedDatabaseName = window.localStorage.getItem(
            databaseNameStorageKey(teamLogic.values.currentTeamId)
        )
        if (persistedDatabaseName) {
            actions.setLastRequestedDatabaseName(persistedDatabaseName)
        }
        actions.loadWarehouseStatus()
    }),
])
