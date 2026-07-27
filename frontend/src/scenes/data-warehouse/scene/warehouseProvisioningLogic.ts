import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { addProductIntent } from 'lib/utils/product-intents'
import { teamLogic } from 'scenes/teamLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { DataWarehouseProvisioningState, DataWarehouseProvisioningStatus } from '~/types'

import type { warehouseProvisioningLogicType } from './warehouseProvisioningLogicType'

const databaseNameStorageKey = (teamId: number | null): string =>
    `warehouse-provisioning-database-name-${teamId ?? 'unknown'}`

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
        setPreviousWarehouseState: (state: DataWarehouseProvisioningState | null) => ({ state }),
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
        // Tracks the last observed provisioning state so we can emit lifecycle telemetry
        // only on genuine transitions (e.g. provisioning -> ready), not on every 10s poll
        // or on mount for a warehouse that was already provisioned in a previous session.
        previousWarehouseState: [
            null as DataWarehouseProvisioningState | null,
            {
                setPreviousWarehouseState: (_, { state }) => state,
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
                actions.setLastRequestedDatabaseName(databaseName)
                window.localStorage.setItem(databaseNameStorageKey(teamLogic.values.currentTeamId), databaseName)
                posthog.capture('managed warehouse provision started', {
                    is_retry: values.warehouseStatus?.state === 'failed',
                })
                try {
                    const result = await api.dataWarehouse.provisionWarehouse(databaseName)
                    if (result.password) {
                        actions.setInitialPassword(result.password)
                    }
                    // Requesting a managed warehouse is a deliberate, settings-deep action, so it's
                    // our genuine intent signal for this product (distinct from data warehouse imports).
                    addProductIntent({
                        product_type: ProductKey.MANAGED_WAREHOUSE,
                        intent_context: ProductIntentContext.MANAGED_WAREHOUSE_PROVISIONED,
                    })
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
                    const result = await api.dataWarehouse.resetPassword()
                    if (result.password) {
                        actions.setInitialPassword(result.password)
                    }
                    posthog.capture('managed warehouse password reset')
                    lemonToast.success('Password has been reset')
                } catch (e: any) {
                    lemonToast.error(`Failed to reset password: ${e.message || 'Unknown error'}`)
                }
                actions.resetPasswordComplete()
            },

            deprovisionWarehouse: async () => {
                window.localStorage.removeItem(databaseNameStorageKey(teamLogic.values.currentTeamId))
                posthog.capture('managed warehouse deprovision started')
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
                // Emit outcome telemetry only on genuine transitions, comparing against the
                // previously observed state (see the `previousWarehouseState` reducer).
                const previousState = values.previousWarehouseState
                const newState = warehouseStatus?.state ?? null
                if ((previousState === 'pending' || previousState === 'provisioning') && newState === 'ready') {
                    posthog.capture('managed warehouse provisioned')
                }
                if (previousState === 'deleting' && newState === 'deleted') {
                    posthog.capture('managed warehouse deprovisioned')
                }
                actions.setPreviousWarehouseState(newState)

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
