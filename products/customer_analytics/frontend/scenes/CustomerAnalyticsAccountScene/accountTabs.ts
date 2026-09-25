import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import {
    listAvailableAccountViewComponents,
    type AccountViewComponentKind,
} from '../../components/Accounts/accountViewComponents'
import type { AccountDetailTabsConfigApi, AccountViewApi } from '../../generated/api.schemas'

export interface AccountTabDefinition {
    id: string
    routeKey: string
    label: string
    kind: 'system' | 'view'
    systemKind?: AccountViewComponentKind
    view?: AccountViewApi
}

export function listAccountTabs(featureFlags: FeatureFlagsSet, views: AccountViewApi[]): AccountTabDefinition[] {
    return [
        ...listAvailableAccountViewComponents(featureFlags).map(
            (component): AccountTabDefinition => ({
                id: component.systemTabId,
                routeKey: component.kind,
                label: component.label,
                kind: 'system',
                systemKind: component.kind,
            })
        ),
        ...views.map(
            (view): AccountTabDefinition => ({
                id: `view:${view.id}`,
                routeKey: `view:${view.id}`,
                label: view.name,
                kind: 'view',
                view,
            })
        ),
    ]
}

function usesTabConfiguration(tab: AccountTabDefinition, applySystemTabConfiguration: boolean): boolean {
    return applySystemTabConfiguration || tab.kind !== 'system'
}

function isUnselectedTeamView(
    tab: AccountTabDefinition,
    config: AccountDetailTabsConfigApi,
    userId: number | undefined
): boolean {
    return tab.view?.visibility === 'team' && tab.view.created_by !== userId && !config.ordered_tab_ids.includes(tab.id)
}

export function listOrderedAccountTabs(
    tabs: AccountTabDefinition[],
    config: AccountDetailTabsConfigApi,
    applySystemTabConfiguration = true
): AccountTabDefinition[] {
    const byId = new Map(tabs.map((tab) => [tab.id, tab]))
    const ordered = config.ordered_tab_ids.flatMap((id) => {
        const tab = byId.get(id)
        if (!tab || !usesTabConfiguration(tab, applySystemTabConfiguration)) {
            return []
        }
        byId.delete(id)
        return [tab]
    })
    return [...ordered, ...tabs.filter((tab) => byId.has(tab.id))]
}

export function isAccountTabVisible(
    tab: AccountTabDefinition,
    config: AccountDetailTabsConfigApi,
    userId: number | undefined,
    applySystemTabConfiguration = true
): boolean {
    const hidden = usesTabConfiguration(tab, applySystemTabConfiguration) && config.hidden_tab_ids.includes(tab.id)
    return !hidden && !isUnselectedTeamView(tab, config, userId)
}

export function listVisibleAccountTabs(
    tabs: AccountTabDefinition[],
    config: AccountDetailTabsConfigApi,
    activeTabId: string | undefined,
    userId: number | undefined,
    applySystemTabConfiguration = true
): AccountTabDefinition[] {
    return listOrderedAccountTabs(tabs, config, applySystemTabConfiguration).filter(
        (tab) => isAccountTabVisible(tab, config, userId, applySystemTabConfiguration) || tab.id === activeTabId
    )
}

export function setAccountTabVisibility(
    tabs: AccountTabDefinition[],
    tab: AccountTabDefinition,
    config: AccountDetailTabsConfigApi,
    userId: number | undefined,
    visible: boolean
): AccountDetailTabsConfigApi {
    const shouldOptIntoTeamView = visible && isUnselectedTeamView(tab, config, userId)
    const orderedTabIds = shouldOptIntoTeamView
        ? tabs.filter((candidate) => !isUnselectedTeamView(candidate, config, userId)).map((candidate) => candidate.id)
        : config.ordered_tab_ids
    return {
        ...config,
        ordered_tab_ids: shouldOptIntoTeamView ? [...orderedTabIds, tab.id] : orderedTabIds,
        hidden_tab_ids: visible
            ? config.hidden_tab_ids.filter((id) => id !== tab.id)
            : [...new Set([...config.hidden_tab_ids, tab.id])],
        default_tab_id: !visible && config.default_tab_id === tab.id ? null : config.default_tab_id,
    }
}

export function moveAccountTab(
    tabs: AccountTabDefinition[],
    config: AccountDetailTabsConfigApi,
    userId: number | undefined,
    tabId: string,
    direction: 'up' | 'down'
): AccountDetailTabsConfigApi {
    const reorderableTabs = tabs.filter((tab) => !isUnselectedTeamView(tab, config, userId) || tab.id === tabId)
    const orderedTabIds = reorderableTabs.map((tab) => tab.id)
    const index = orderedTabIds.indexOf(tabId)
    const nextIndex = direction === 'up' ? index - 1 : index + 1
    if (index < 0 || nextIndex < 0 || nextIndex >= orderedTabIds.length) {
        return config
    }
    ;[orderedTabIds[index], orderedTabIds[nextIndex]] = [orderedTabIds[nextIndex], orderedTabIds[index]]
    return { ...config, ordered_tab_ids: orderedTabIds }
}

export function getAccountTabIdFromRoute(routeKey: string): string {
    return routeKey.startsWith('view:') ? routeKey : `system:${routeKey}`
}

export function getAccountTabRoute(tabId: string): string {
    return tabId.startsWith('system:') ? tabId.slice('system:'.length) : tabId
}

export function getDefaultAccountTabId(
    tabs: AccountTabDefinition[],
    config: AccountDetailTabsConfigApi,
    applySystemTabConfiguration = true
): string {
    const defaultTab = tabs.find((tab) => tab.id === config.default_tab_id)
    if (
        defaultTab &&
        usesTabConfiguration(defaultTab, applySystemTabConfiguration) &&
        !config.hidden_tab_ids.includes(defaultTab.id)
    ) {
        return defaultTab.id
    }
    return (
        tabs.find(
            (tab) => tab.kind === 'system' && isAccountTabVisible(tab, config, undefined, applySystemTabConfiguration)
        )?.id ??
        tabs.find((tab) => tab.kind === 'system')?.id ??
        'system:notes'
    )
}

export function getActiveAccountTabId(
    tabs: AccountTabDefinition[],
    config: AccountDetailTabsConfigApi,
    requestedTabId: string | undefined,
    applySystemTabConfiguration = true
): string {
    const defaultTabId = getDefaultAccountTabId(tabs, config, applySystemTabConfiguration)
    if (!requestedTabId || !requestedTabId.startsWith('system:')) {
        return requestedTabId ?? defaultTabId
    }
    return tabs.some((tab) => tab.id === requestedTabId) ? requestedTabId : defaultTabId
}
