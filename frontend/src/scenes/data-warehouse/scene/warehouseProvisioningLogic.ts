import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { DataWarehouseProvisioningStatus } from '~/types'

import type { warehouseProvisioningLogicType } from './warehouseProvisioningLogicType'

export const warehouseProvisioningLogic = kea<warehouseProvisioningLogicType>([
    path(['scenes', 'data-warehouse', 'scene', 'warehouseProvisioningLogic']),

    actions({
        provisionWarehouse: (params: { databaseName: string }) => params,
        provisionWarehouseComplete: true,
        deprovisionWarehouse: true,
        deprovisionWarehouseComplete: true,
        pollStatus: true,
        stopPolling: true,
        setDatabaseName: (name: string) => ({ name }),
        checkDatabaseName: (name: string) => ({ name }),
        setDatabaseNameAvailable: (available: boolean | null) => ({ available }),
        setDatabaseNameChecking: (checking: boolean) => ({ checking }),
    }),

    loaders({
        warehouseStatus: [
            null as DataWarehouseProvisioningStatus | null,
            {
                loadWarehouseStatus: async () => {
                    try {
                        return await api.dataWarehouse.warehouseStatus()
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
        isValidDatabaseName: [(s) => [s.databaseName], (name): boolean => /^[a-z][a-z0-9_-]{2,62}$/.test(name)],
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
                if (/^[a-z][a-z0-9_-]{2,62}$/.test(name)) {
                    actions.setDatabaseNameChecking(true)
                    debounceTimer = setTimeout(() => {
                        actions.checkDatabaseName(name)
                    }, 400)
                }
            },

            checkDatabaseName: async ({ name }) => {
                try {
                    const result = await api.dataWarehouse.checkDatabaseName(name)
                    if (values.databaseName === name) {
                        actions.setDatabaseNameAvailable(result.available)
                    }
                } catch {
                    actions.setDatabaseNameAvailable(null)
                }
                actions.setDatabaseNameChecking(false)
            },

            provisionWarehouse: async ({ databaseName }) => {
                try {
                    await api.dataWarehouse.provisionWarehouse(databaseName)
                    lemonToast.success('Warehouse provisioning started')
                    actions.loadWarehouseStatus()
                    actions.pollStatus()
                } catch (e: any) {
                    lemonToast.error(`Failed to provision warehouse: ${e.message || 'Unknown error'}`)
                }
                actions.provisionWarehouseComplete()
            },

            deprovisionWarehouse: async () => {
                try {
                    await api.dataWarehouse.deprovisionWarehouse()
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
        actions.loadWarehouseStatus()
    }),
])
