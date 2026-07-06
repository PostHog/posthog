import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'

import { Region } from '~/types'

import {
    dataWarehouseCheckDatabaseNameRetrieve,
    dataWarehouseDeleteOrgDestroy,
    dataWarehouseDeprovisionCreate,
    dataWarehouseEnableBackfillCreate,
    dataWarehouseProvisionCreate,
    dataWarehouseResetPasswordCreate,
    dataWarehouseWarehouseStatusRetrieve,
} from 'products/data_warehouse/frontend/generated/api'
import type { WarehouseStatusResponseApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import type { warehouseProvisioningLogicType } from './warehouseProvisioningLogicType'

// The warehouse name becomes the connection's SNI subdomain (a DNS-1123 label), so it
// mirrors the backend validator in products/data_warehouse/backend/api/managed_warehouse.py:
// 3-63 chars, lowercase alphanumerics and hyphens, starting/ending alphanumeric (no underscores).
const WAREHOUSE_NAME_REGEX = /^[a-z][a-z0-9-]{1,61}[a-z0-9]$/

// DNS zone the connection host lives under, selected by deployment region. Mirrors
// _MANAGED_WAREHOUSE_DOMAINS in products/data_warehouse/backend/api/managed_warehouse.py.
const MANAGED_WAREHOUSE_DOMAINS: Partial<Record<Region, string>> = {
    [Region.US]: 'us.postwh.com',
    [Region.EU]: 'eu.postwh.com',
    [Region.DEV]: 'dev.postwh.com',
}

// The table name is used verbatim as the suffix in events_<suffix> / persons_<suffix>, so it
// must already be a safe SQL identifier. Mirrors validate_table_suffix in posthog/ducklake/common.py.
const TABLE_NAME_REGEX = /^[a-z0-9_]{1,63}$/

const databaseNameStorageKey = (teamId: number | null): string =>
    `warehouse-provisioning-database-name-${teamId ?? 'unknown'}`

// Status is polled every 10s. Deprovision teardown has no terminal `failed` state (the
// provisioner retries indefinitely), so a genuinely stuck teardown sits in `deleting` forever.
// After this many consecutive `deleting` polls (~3 min) we surface a "still working" affordance
// instead of spinning silently. It's advisory only; polling continues.
const DELETING_POLL_WARN_THRESHOLD = 18

const currentProjectId = (): string => String(teamLogic.values.currentTeamId)

export const warehouseProvisioningLogic = kea<warehouseProvisioningLogicType>([
    path(['scenes', 'data-warehouse', 'scene', 'warehouseProvisioningLogic']),

    connect(() => ({
        values: [preflightLogic, ['preflight']],
    })),

    actions({
        provisionWarehouse: (params: { databaseName: string; tableName: string }) => params,
        provisionWarehouseComplete: true,
        deprovisionWarehouse: true,
        deprovisionWarehouseComplete: true,
        deleteOrg: true,
        deleteOrgComplete: true,
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
        setTableName: (name: string) => ({ name }),
        enableBackfill: (params: { tableName: string }) => params,
        enableBackfillComplete: (suffix: string | null) => ({ suffix }),
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
        // Consecutive `deleting` status reads, to detect a teardown that's stuck (no terminal
        // failed state exists, so it would otherwise poll forever). Reset whenever the state
        // isn't `deleting` and when a fresh deprovision starts.
        deletingPollCount: [
            0,
            {
                loadWarehouseStatusSuccess: (state, { warehouseStatus }) =>
                    warehouseStatus?.state === 'deleting' ? state + 1 : 0,
                deprovisionWarehouse: () => 0,
            },
        ],
        // Guards the automatic delete-org call so it fires once per `deleted` observation
        // rather than on every re-render/poll. Cleared when a new deprovision starts.
        orgDeletionRequested: [
            false,
            {
                deleteOrg: () => true,
                deprovisionWarehouse: () => false,
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
        tableName: [
            '',
            {
                setTableName: (_, { name }) => name,
            },
        ],
        isEnablingBackfill: [
            false,
            {
                enableBackfill: () => true,
                enableBackfillComplete: () => false,
            },
        ],
        backfillTableSuffix: [
            null as string | null,
            {
                loadWarehouseStatusSuccess: (_, { warehouseStatus }) => warehouseStatus?.table_suffix ?? null,
                enableBackfillComplete: (state, { suffix }) => suffix ?? state,
                deprovisionWarehouse: () => null,
            },
        ],
        // Whether this project already has a backfill configured. When true, the table name is
        // fixed (immutable), so we show a read-only state instead of re-offering the enable form.
        hasBackfill: [
            false,
            {
                loadWarehouseStatusSuccess: (_, { warehouseStatus }) => warehouseStatus?.has_backfill ?? false,
                enableBackfillComplete: (state, { suffix }) => (suffix ? true : state),
                deprovisionWarehouse: () => false,
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
        // True once teardown has sat in `deleting` past the warn threshold, so the UI can show a
        // "still working" note rather than an indefinite spinner.
        deprovisionTakingLong: [
            (s) => [s.warehouseStatus, s.deletingPollCount],
            (status, deletingPollCount): boolean =>
                status?.state === 'deleting' && deletingPollCount >= DELETING_POLL_WARN_THRESHOLD,
        ],
        isValidDatabaseName: [(s) => [s.databaseName], (name): boolean => WAREHOUSE_NAME_REGEX.test(name)],
        // DNS zone for the connection host, resolved from the deployment region (null when unknown).
        warehouseDomain: [
            (s) => [s.preflight],
            (preflight): string | null => {
                const region = preflight?.region
                return region ? (MANAGED_WAREHOUSE_DOMAINS[region] ?? null) : null
            },
        ],
        retryDatabaseName: [
            (s) => [s.databaseName, s.lastRequestedDatabaseName],
            (databaseName, lastRequestedDatabaseName): string => databaseName || lastRequestedDatabaseName || '',
        ],
        // The table name is used verbatim as the table suffix, so it must already be a valid
        // identifier (mirrors the backend validator) — we reject rather than silently rewrite.
        isValidTableName: [(s) => [s.tableName], (name): boolean => TABLE_NAME_REGEX.test(name)],
        canProvision: [
            (s) => [s.isValidDatabaseName, s.databaseNameAvailable, s.isValidTableName],
            (valid, available, validEvents): boolean => valid && available === true && validEvents,
        ],
        canRetryProvision: [
            (s) => [s.retryDatabaseName, s.isValidTableName],
            (retryDatabaseName, validEvents): boolean =>
                !!retryDatabaseName && WAREHOUSE_NAME_REGEX.test(retryDatabaseName) && validEvents,
        ],
    }),

    listeners(({ actions, values }) => {
        let debounceTimer: ReturnType<typeof setTimeout> | null = null

        return {
            setDatabaseName: ({ name }) => {
                if (debounceTimer) {
                    clearTimeout(debounceTimer)
                }
                if (WAREHOUSE_NAME_REGEX.test(name)) {
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

            provisionWarehouse: async ({ databaseName, tableName }) => {
                actions.setLastRequestedDatabaseName(databaseName)
                window.localStorage.setItem(databaseNameStorageKey(teamLogic.values.currentTeamId), databaseName)
                try {
                    const result = await dataWarehouseProvisionCreate(currentProjectId(), {
                        database_name: databaseName,
                        table_name: tableName,
                    })
                    if (result.password) {
                        actions.setInitialPassword(result.password)
                    }
                    lemonToast.success('Warehouse provisioning started')
                    actions.loadWarehouseStatus()
                    actions.pollStatus()
                } catch (e: any) {
                    if (e.status === 409) {
                        // Another project in this organization already provisioned the shared warehouse.
                        lemonToast.info('This organization already has a managed warehouse')
                        actions.loadWarehouseStatus()
                        actions.pollStatus()
                    } else {
                        lemonToast.error(`Failed to provision warehouse: ${e.message || 'Unknown error'}`)
                    }
                }
                actions.provisionWarehouseComplete()
            },

            enableBackfill: async ({ tableName }) => {
                try {
                    const result = await dataWarehouseEnableBackfillCreate(currentProjectId(), {
                        table_name: tableName,
                    })
                    lemonToast.success('Warehouse backfill enabled for this project')
                    actions.enableBackfillComplete(result.table_suffix ?? null)
                    // Refresh from the server so the read-only state reflects the now-fixed table.
                    actions.loadWarehouseStatus()
                } catch (e: any) {
                    lemonToast.error(`Failed to enable backfill: ${e.detail || e.message || 'Unknown error'}`)
                    actions.enableBackfillComplete(null)
                }
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

            deleteOrg: async () => {
                try {
                    // Teardown is done (status is `deleted`); remove the now-empty org record so
                    // its database_name is freed. On success the next status read 404s and the UI
                    // returns to the provisioning form.
                    await dataWarehouseDeleteOrgDestroy(currentProjectId())
                    actions.loadWarehouseStatus()
                } catch (e: any) {
                    lemonToast.error(`Failed to finish removing the warehouse: ${e.message || 'Unknown error'}`)
                }
                actions.deleteOrgComplete()
            },

            loadWarehouseStatusSuccess: ({ warehouseStatus }) => {
                if (warehouseStatus?.state === 'deleted') {
                    actions.setLastRequestedDatabaseName(null)
                    window.localStorage.removeItem(databaseNameStorageKey(teamLogic.values.currentTeamId))
                    // Teardown finished, so remove the org row to free the name. Guarded so it fires
                    // once, not on every poll/re-render that still reports `deleted`.
                    if (!values.orgDeletionRequested) {
                        actions.deleteOrg()
                    }
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
        // Prefill the table name with a valid default derived from the project name (lowercased,
        // non-identifier chars collapsed to underscores). It's only a starting point — the user
        // edits/confirms it, and the input is validated verbatim from there.
        const projectName = teamLogic.values.currentTeam?.name
        const defaultTableName = projectName
            ?.toLowerCase()
            .replace(/[^a-z0-9_]+/g, '_')
            .replace(/^_+|_+$/g, '')
            .slice(0, 63)
        if (defaultTableName) {
            actions.setTableName(defaultTableName)
        }
        actions.loadWarehouseStatus()
    }),
])
