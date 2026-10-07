import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import {
    listAvailableAccountViewSystemComponents,
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
        ...listAvailableAccountViewSystemComponents(featureFlags).map(
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

function isUnselectedTeamView(
    tab: AccountTabDefinition,
    config: AccountDetailTabsConfigApi,
    userId: number | undefined
): boolean {
    return tab.view?.visibility === 'team' && tab.view.created_by !== userId && !config.ordered_tab_ids.includes(tab.id)
}

function sortAccountTabsByConfig(
    tabs: AccountTabDefinition[],
    config: AccountDetailTabsConfigApi
): AccountTabDefinition[] {
    const byId = new Map(tabs.map((tab) => [tab.id, tab]))
    const ordered = config.ordered_tab_ids.flatMap((id) => {
        const tab = byId.get(id)
        if (!tab) {
            return []
        }
        byId.delete(id)
        return [tab]
    })
    return [...ordered, ...tabs.filter((tab) => byId.has(tab.id))]
}

export function listOrderedAccountTabs(
    tabs: AccountTabDefinition[],
    config: AccountDetailTabsConfigApi,
    applyTabConfiguration = true
): AccountTabDefinition[] {
    const orderedTabs = applyTabConfiguration ? sortAccountTabsByConfig(tabs, config) : tabs
    return [...orderedTabs.filter((tab) => tab.kind === 'view'), ...orderedTabs.filter((tab) => tab.kind === 'system')]
}

export function isAccountTabVisible(
    tab: AccountTabDefinition,
    config: AccountDetailTabsConfigApi,
    userId: number | undefined,
    applyTabConfiguration = true
): boolean {
    if (!applyTabConfiguration) {
        return true
    }
    return !config.hidden_tab_ids.includes(tab.id) && !isUnselectedTeamView(tab, config, userId)
}

export function listVisibleAccountTabs(
    tabs: AccountTabDefinition[],
    config: AccountDetailTabsConfigApi,
    activeTabId: string | undefined,
    userId: number | undefined,
    applyTabConfiguration = true
): AccountTabDefinition[] {
    return listOrderedAccountTabs(tabs, config, applyTabConfiguration).filter(
        (tab) => isAccountTabVisible(tab, config, userId, applyTabConfiguration) || tab.id === activeTabId
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

export function reorderAccountTab(
    tabs: AccountTabDefinition[],
    config: AccountDetailTabsConfigApi,
    userId: number | undefined,
    activeTabId: string,
    overTabId: string
): AccountDetailTabsConfigApi {
    const orderedTabs = listOrderedAccountTabs(tabs, config)
    const fromIndex = orderedTabs.findIndex((tab) => tab.id === activeTabId)
    const toIndex = orderedTabs.findIndex((tab) => tab.id === overTabId)
    if (
        fromIndex < 0 ||
        toIndex < 0 ||
        fromIndex === toIndex ||
        orderedTabs[fromIndex].kind !== orderedTabs[toIndex].kind
    ) {
        return config
    }
    const reorderedTabs = [...orderedTabs]
    const [moved] = reorderedTabs.splice(fromIndex, 1)
    reorderedTabs.splice(toIndex, 0, moved)
    return {
        ...config,
        ordered_tab_ids: reorderedTabs
            .filter((tab) => !isUnselectedTeamView(tab, config, userId) || tab.id === activeTabId)
            .map((tab) => tab.id),
    }
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
    userId: number | undefined,
    applyTabConfiguration = true
): string {
    const defaultTab = tabs.find((tab) => tab.id === config.default_tab_id)
    if (defaultTab && applyTabConfiguration && !config.hidden_tab_ids.includes(defaultTab.id)) {
        return defaultTab.id
    }
    const isVisible = (tab: AccountTabDefinition): boolean =>
        isAccountTabVisible(tab, config, userId, applyTabConfiguration)
    return (
        tabs.find((tab) => tab.kind === 'system' && isVisible(tab))?.id ??
        listOrderedAccountTabs(tabs, config, applyTabConfiguration).find(isVisible)?.id ??
        tabs.find((tab) => tab.kind === 'system')?.id ??
        'system:notes'
    )
}

export function getActiveAccountTabId(
    tabs: AccountTabDefinition[],
    config: AccountDetailTabsConfigApi,
    requestedTabId: string | undefined,
    userId: number | undefined,
    applyTabConfiguration = true
): string {
    const defaultTabId = getDefaultAccountTabId(tabs, config, userId, applyTabConfiguration)
    if (!requestedTabId || !requestedTabId.startsWith('system:')) {
        return requestedTabId ?? defaultTabId
    }
    return tabs.some((tab) => tab.id === requestedTabId) ? requestedTabId : defaultTabId
}
