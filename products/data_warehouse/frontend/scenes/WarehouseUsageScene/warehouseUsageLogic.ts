import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import {
    managedWarehouseConsoleSettingsPartialUpdate,
    managedWarehouseConsoleSettingsRetrieve,
    managedWarehouseConsoleUsageRetrieve,
} from 'products/data_warehouse/frontend/generated/api'
import type {
    ConsoleSettingsApi,
    ManagedWarehouseConsoleUsageRetrieveGroupBy,
    ManagedWarehouseConsoleUsageRetrievePeriod,
    UsageBreakdownApi,
    UsageDailyApi,
    UsageSummaryApi,
} from 'products/data_warehouse/frontend/generated/api.schemas'

import { consoleErrorMessage } from '../WarehouseConsole/consoleErrorMessage'
import { GIB, parseDecimal } from '../WarehouseConsole/warehouseConsoleFormat'
import { warehouseConsoleLogic } from '../WarehouseConsole/warehouseConsoleLogic'
import type { WarehouseConsoleState } from '../WarehouseConsole/warehouseConsoleLogic'

export type UsagePeriod = ManagedWarehouseConsoleUsageRetrievePeriod
export type UsageGroupBy = ManagedWarehouseConsoleUsageRetrieveGroupBy

export interface UsageMeter {
    used: number
    free: number
    /** Share of the free allowance used, 0 to 100 or more. Null when there is no allowance to compare with. */
    percent: number | null
    overFree: boolean
}

export interface BreakdownRow extends UsageBreakdownApi {
    /** Share of all billable bytes in the breakdown, 0 to 1. */
    shareOfBytes: number
}

export interface UsageChartData {
    labels: string[]
    billableBytes: number[]
    storageAverageBytes: number[]
}

/** The cap must stay at or above the smallest value the API accepts. */
export const MIN_SCAN_CAP_GIB = 1

export function buildMeter(used: number, free: number): UsageMeter {
    return {
        used,
        free,
        percent: free > 0 ? (used / free) * 100 : null,
        overFree: free > 0 && used > free,
    }
}

/** The first day on which the running total of billable bytes passes the free allowance. */
export function findFreeAllowanceCrossing(daily: UsageDailyApi[], freeBytes: number): string | null {
    if (freeBytes <= 0) {
        return null
    }
    let cumulative = 0
    for (const day of daily) {
        cumulative += day.billable_bytes
        if (cumulative > freeBytes) {
            return day.date
        }
    }
    return null
}

export type SpendControlsDraftError = { field: 'budget' | 'scanCap'; message: string }

/** Turns the two text inputs into an API payload. An empty input removes that limit. */
export function parseSpendControls(
    budgetInput: string,
    scanCapGibInput: string
):
    | { payload: { monthly_budget_usd: string | null; max_scan_bytes_per_query: number | null } }
    | SpendControlsDraftError {
    const budgetText = budgetInput.trim()
    let monthlyBudget: string | null = null
    if (budgetText !== '') {
        if (!/^\d{1,10}(\.\d{1,2})?$/.test(budgetText)) {
            return { field: 'budget', message: 'Enter a dollar amount with up to two decimals.' }
        }
        monthlyBudget = parseDecimal(budgetText).toFixed(2)
    }
    const capText = scanCapGibInput.trim()
    let maxScanBytes: number | null = null
    if (capText !== '') {
        const gib = /^\d+(\.\d+)?$/.test(capText) ? Number(capText) : Number.NaN
        if (!Number.isFinite(gib) || gib < MIN_SCAN_CAP_GIB) {
            return {
                field: 'scanCap',
                message: `Enter at least ${MIN_SCAN_CAP_GIB} GiB, or leave it empty for no cap.`,
            }
        }
        maxScanBytes = Math.round(gib * GIB)
    }
    return { payload: { monthly_budget_usd: monthlyBudget, max_scan_bytes_per_query: maxScanBytes } }
}

/** Only the limits the admin changed, so saving one never rewrites or clears the other. */
export function changedSettings(
    payload: { monthly_budget_usd: string | null; max_scan_bytes_per_query: number | null },
    saved: ConsoleSettingsApi
): Partial<{ monthly_budget_usd: string | null; max_scan_bytes_per_query: number | null }> {
    const patch: Partial<{ monthly_budget_usd: string | null; max_scan_bytes_per_query: number | null }> = {}
    const budgetChanged =
        payload.monthly_budget_usd === null || saved.monthly_budget_usd === null
            ? payload.monthly_budget_usd !== saved.monthly_budget_usd
            : parseDecimal(payload.monthly_budget_usd) !== parseDecimal(saved.monthly_budget_usd)
    if (budgetChanged) {
        patch.monthly_budget_usd = payload.monthly_budget_usd
    }
    if (payload.max_scan_bytes_per_query !== saved.max_scan_bytes_per_query) {
        patch.max_scan_bytes_per_query = payload.max_scan_bytes_per_query
    }
    return patch
}

function budgetToInput(settings: ConsoleSettingsApi | null): string {
    return settings?.monthly_budget_usd == null ? '' : parseDecimal(settings.monthly_budget_usd).toFixed(2)
}

function scanCapToInput(settings: ConsoleSettingsApi | null): string {
    return settings?.max_scan_bytes_per_query == null ? '' : String(settings.max_scan_bytes_per_query / GIB)
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface warehouseUsageLogicValues {
    isAdminOrOwner: boolean | null // organizationLogic
    currentTeamId: number | null // teamLogic
    consoleState: WarehouseConsoleState // warehouseConsoleLogic
    breakdownRows: BreakdownRow[]
    budgetDraft: string | null
    budgetInput: string
    budgetPercent: number | null
    canEditSpendControls: boolean
    chartData: UsageChartData
    computeMeter: UsageMeter | null
    freeAllowanceCrossingDate: string | null
    groupBy: UsageGroupBy
    isCurrentMonth: boolean
    isSavingSpendControls: boolean
    period: UsagePeriod
    scanCapDraft: string | null
    scanCapInput: string
    settings: ConsoleSettingsApi | null
    settingsFailed: boolean
    settingsLoading: boolean
    spendControlsDirty: boolean
    spendControlsError: SpendControlsDraftError | null
    spendControlsParse:
        | SpendControlsDraftError
        | {
              payload: {
                  max_scan_bytes_per_query: number | null
                  monthly_budget_usd: string | null
              }
          }
    storageMeter: UsageMeter | null
    usage: UsageSummaryApi | null
    usageFailed: boolean
    usageLoading: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface warehouseUsageLogicActions {
    loadWarehouseStatusSuccess: (
        warehouseStatus:
            | null
            | import('products/data_warehouse/frontend/generated/api.schemas').WarehouseStatusResponseApi,
        payload?: any
    ) => {
        payload?: any
        warehouseStatus:
            | null
            | import('products/data_warehouse/frontend/generated/api.schemas').WarehouseStatusResponseApi
    } // warehouseConsoleLogic
    ensureLoaded: () => {
        value: true
    }
    loadSettings: () => any
    loadSettingsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadSettingsSuccess: (
        settings: ConsoleSettingsApi,
        payload?: any
    ) => {
        settings: ConsoleSettingsApi
        payload?: any
    }
    loadUsage: (_: void) => void
    loadUsageFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadUsageSuccess: (
        usage: UsageSummaryApi,
        payload?: void
    ) => {
        usage: UsageSummaryApi
        payload?: void
    }
    resetSpendControls: () => {
        value: true
    }
    retrySettings: () => {
        value: true
    }
    retryUsage: () => {
        value: true
    }
    saveSpendControls: () => {
        value: true
    }
    saveSpendControlsFailure: () => {
        value: true
    }
    saveSpendControlsSuccess: (settings: ConsoleSettingsApi) => {
        settings: ConsoleSettingsApi
    }
    setBudgetInput: (value: string) => {
        value: string
    }
    setGroupBy: (groupBy: UsageGroupBy) => {
        groupBy: ManagedWarehouseConsoleUsageRetrieveGroupBy
    }
    setPeriod: (period: UsagePeriod) => {
        period: ManagedWarehouseConsoleUsageRetrievePeriod
    }
    setScanCapInput: (value: string) => {
        value: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface warehouseUsageLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        computeMeter: (usage: UsageSummaryApi | null) => UsageMeter | null
        storageMeter: (usage: UsageSummaryApi | null) => UsageMeter | null
        budgetPercent: (usage: UsageSummaryApi | null) => number | null
        isCurrentMonth: (period: ManagedWarehouseConsoleUsageRetrievePeriod) => boolean
        chartData: (usage: UsageSummaryApi | null) => UsageChartData
        freeAllowanceCrossingDate: (usage: UsageSummaryApi | null) => string | null
        breakdownRows: (usage: UsageSummaryApi | null) => BreakdownRow[]
        budgetInput: (budgetDraft: string | null, settings: ConsoleSettingsApi | null) => string
        scanCapInput: (scanCapDraft: string | null, settings: ConsoleSettingsApi | null) => string
        spendControlsParse: (
            budgetInput: string,
            scanCapInput: string
        ) =>
            | SpendControlsDraftError
            | {
                  payload: {
                      max_scan_bytes_per_query: number | null
                      monthly_budget_usd: string | null
                  }
              }
        spendControlsError: (
            spendControlsParse:
                | SpendControlsDraftError
                | {
                      payload: {
                          max_scan_bytes_per_query: number | null
                          monthly_budget_usd: string | null
                      }
                  }
        ) => SpendControlsDraftError | null
        spendControlsDirty: (budgetInput: string, scanCapInput: string, settings: ConsoleSettingsApi | null) => boolean
        canEditSpendControls: (isAdminOrOwner: boolean | null) => boolean
    }
}

export type warehouseUsageLogicType = MakeLogicType<
    warehouseUsageLogicValues,
    warehouseUsageLogicActions,
    Record<string, any>,
    warehouseUsageLogicMeta
>

export const warehouseUsageLogic = kea<warehouseUsageLogicType>([
    path(['products', 'data_warehouse', 'frontend', 'scenes', 'WarehouseUsageScene', 'warehouseUsageLogic']),
    connect(() => ({
        values: [
            teamLogic,
            ['currentTeamId'],
            organizationLogic,
            ['isAdminOrOwner'],
            warehouseConsoleLogic,
            ['consoleState'],
        ],
        actions: [warehouseConsoleLogic, ['loadWarehouseStatusSuccess']],
    })),
    actions({
        setPeriod: (period: UsagePeriod) => ({ period }),
        setGroupBy: (groupBy: UsageGroupBy) => ({ groupBy }),
        setBudgetInput: (value: string) => ({ value }),
        setScanCapInput: (value: string) => ({ value }),
        resetSpendControls: true,
        saveSpendControls: true,
        saveSpendControlsSuccess: (settings: ConsoleSettingsApi) => ({ settings }),
        saveSpendControlsFailure: true,
        retryUsage: true,
        ensureLoaded: true,
        retrySettings: true,
    }),
    reducers({
        period: [
            'current_month' as UsagePeriod,
            {
                setPeriod: (_, { period }) => period,
            },
        ],
        groupBy: [
            'source' as UsageGroupBy,
            {
                setGroupBy: (_, { groupBy }) => groupBy,
            },
        ],
        usageFailed: [
            false,
            {
                loadUsage: () => false,
                loadUsageSuccess: () => false,
                loadUsageFailure: () => true,
            },
        ],
        settingsFailed: [
            false,
            {
                loadSettings: () => false,
                loadSettingsSuccess: () => false,
                loadSettingsFailure: () => true,
            },
        ],
        // null means the user has not edited the field, so it shows the saved value.
        budgetDraft: [
            null as string | null,
            {
                setBudgetInput: (_, { value }) => value,
                resetSpendControls: () => null,
                saveSpendControlsSuccess: () => null,
            },
        ],
        scanCapDraft: [
            null as string | null,
            {
                setScanCapInput: (_, { value }) => value,
                resetSpendControls: () => null,
                saveSpendControlsSuccess: () => null,
            },
        ],
        settings: {
            saveSpendControlsSuccess: (_, { settings }) => settings,
        },
        isSavingSpendControls: [
            false,
            {
                saveSpendControls: () => true,
                saveSpendControlsSuccess: () => false,
                saveSpendControlsFailure: () => false,
            },
        ],
    }),
    loaders(({ values }) => ({
        usage: [
            null as UsageSummaryApi | null,
            {
                loadUsage: async (_: void, breakpoint) => {
                    const response = await managedWarehouseConsoleUsageRetrieve(String(values.currentTeamId), {
                        period: values.period,
                        group_by: values.groupBy,
                    })
                    breakpoint()
                    return response
                },
            },
        ],
        settings: [
            null as ConsoleSettingsApi | null,
            {
                loadSettings: async () => await managedWarehouseConsoleSettingsRetrieve(String(values.currentTeamId)),
            },
        ],
    })),
    selectors({
        computeMeter: [
            (s) => [s.usage],
            (usage: UsageSummaryApi | null): UsageMeter | null =>
                usage ? buildMeter(usage.compute.billable_bytes, usage.compute.free_bytes) : null,
        ],
        storageMeter: [
            (s) => [s.usage],
            (usage: UsageSummaryApi | null): UsageMeter | null =>
                usage
                    ? buildMeter(parseDecimal(usage.storage.gib_months), parseDecimal(usage.storage.free_gib_months))
                    : null,
        ],
        budgetPercent: [
            (s) => [s.usage],
            (usage: UsageSummaryApi | null): number | null =>
                usage?.budget.share_used == null ? null : parseDecimal(usage.budget.share_used) * 100,
        ],
        isCurrentMonth: [(s) => [s.period], (period: UsagePeriod): boolean => period === 'current_month'],
        chartData: [
            (s) => [s.usage],
            (usage: UsageSummaryApi | null): UsageChartData => ({
                labels: (usage?.daily ?? []).map((day) => day.date),
                billableBytes: (usage?.daily ?? []).map((day) => day.billable_bytes),
                storageAverageBytes: (usage?.daily ?? []).map((day) => day.storage_average_bytes),
            }),
        ],
        freeAllowanceCrossingDate: [
            (s) => [s.usage],
            (usage: UsageSummaryApi | null): string | null =>
                usage ? findFreeAllowanceCrossing(usage.daily, usage.compute.free_bytes) : null,
        ],
        breakdownRows: [
            (s) => [s.usage],
            (usage: UsageSummaryApi | null): BreakdownRow[] => {
                const rows = usage?.breakdown ?? []
                const totalBytes = rows.reduce((sum, row) => sum + row.billable_bytes, 0)
                return rows.map((row) => ({
                    ...row,
                    shareOfBytes: totalBytes > 0 ? row.billable_bytes / totalBytes : 0,
                }))
            },
        ],
        budgetInput: [
            (s) => [s.budgetDraft, s.settings],
            (draft: string | null, settings: ConsoleSettingsApi | null): string => draft ?? budgetToInput(settings),
        ],
        scanCapInput: [
            (s) => [s.scanCapDraft, s.settings],
            (draft: string | null, settings: ConsoleSettingsApi | null): string => draft ?? scanCapToInput(settings),
        ],
        spendControlsParse: [
            (s) => [s.budgetInput, s.scanCapInput],
            (budgetInput: string, scanCapInput: string) => parseSpendControls(budgetInput, scanCapInput),
        ],
        spendControlsError: [
            (s) => [s.spendControlsParse],
            (
                parsed:
                    | SpendControlsDraftError
                    | {
                          payload: {
                              max_scan_bytes_per_query: number | null
                              monthly_budget_usd: string | null
                          }
                      }
            ): SpendControlsDraftError | null => ('field' in parsed ? parsed : null),
        ],
        spendControlsDirty: [
            (s) => [s.budgetInput, s.scanCapInput, s.settings],
            (budgetInput: string, scanCapInput: string, settings: ConsoleSettingsApi | null): boolean =>
                budgetInput.trim() !== budgetToInput(settings) || scanCapInput.trim() !== scanCapToInput(settings),
        ],
        canEditSpendControls: [
            (s) => [s.isAdminOrOwner],
            (isAdminOrOwner: boolean | null): boolean => !!isAdminOrOwner,
        ],
    }),
    listeners(({ actions, values }) => {
        const consoleReady = (): boolean => values.consoleState === 'ready'
        // The usage and the settings load on their own, so one request in flight never hides the other.
        const ensureLoaded = (): void => {
            if (!consoleReady()) {
                return
            }
            if (!values.usage && !values.usageLoading) {
                actions.loadUsage()
            }
            if (!values.settings && !values.settingsLoading) {
                actions.loadSettings()
            }
        }
        return {
            setPeriod: ({ period }) => {
                posthog.capture('warehouse usage period changed', { period })
                if (consoleReady()) {
                    actions.loadUsage()
                }
            },
            setGroupBy: ({ groupBy }) => {
                posthog.capture('warehouse usage grouping changed', { group_by: groupBy })
                if (consoleReady()) {
                    actions.loadUsage()
                }
            },
            retryUsage: () => {
                posthog.capture('warehouse usage retry clicked', { section: 'usage' })
                actions.loadUsage()
            },
            retrySettings: () => {
                posthog.capture('warehouse usage retry clicked', { section: 'spend_controls' })
                actions.loadSettings()
            },
            saveSpendControls: async () => {
                const parsed = values.spendControlsParse
                const saved = values.settings
                if ('field' in parsed || !saved) {
                    actions.saveSpendControlsFailure()
                    return
                }
                const patch = changedSettings(parsed.payload, saved)
                posthog.capture('warehouse spend controls save clicked', {
                    changed_budget: 'monthly_budget_usd' in patch,
                    changed_scan_cap: 'max_scan_bytes_per_query' in patch,
                })
                try {
                    const settings = await managedWarehouseConsoleSettingsPartialUpdate(
                        String(values.currentTeamId),
                        patch
                    )
                    actions.saveSpendControlsSuccess(settings)
                    posthog.capture('warehouse spend controls saved')
                    lemonToast.success('Spend controls saved')
                    // The budget meter on the page depends on the saved budget.
                    actions.loadUsage()
                } catch (error: any) {
                    posthog.capture('warehouse spend controls save failed')
                    lemonToast.error(consoleErrorMessage(error, 'Could not save spend controls. Try again.'))
                    actions.saveSpendControlsFailure()
                }
            },
            loadWarehouseStatusSuccess: ensureLoaded,
            ensureLoaded,
        }
    }),
    actionToUrl(() => ({
        setGroupBy: ({ groupBy }) => [
            urls.warehouseUsage(),
            groupBy === 'source' ? {} : { group_by: groupBy },
            undefined,
            { replace: true },
        ],
    })),
    // The home page links here with `?group_by=principal`.
    urlToAction(({ actions, values }) => ({
        [urls.warehouseUsage()]: (_, searchParams) => {
            const groupBy = searchParams.group_by
            if ((groupBy === 'principal' || groupBy === 'team') && values.groupBy !== groupBy) {
                actions.setGroupBy(groupBy)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.ensureLoaded()
    }),
])
