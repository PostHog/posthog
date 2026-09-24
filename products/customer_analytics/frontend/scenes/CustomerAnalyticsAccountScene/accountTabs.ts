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

export function listOrderedAccountTabs(
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

export function listVisibleAccountTabs(
    tabs: AccountTabDefinition[],
    config: AccountDetailTabsConfigApi,
    activeTabId: string | undefined,
    userId: number | undefined
): AccountTabDefinition[] {
    const hidden = new Set(config.hidden_tab_ids)
    const selected = new Set(config.ordered_tab_ids)
    return listOrderedAccountTabs(tabs, config).filter((tab) => {
        const unselectedTeamView =
            tab.view?.visibility === 'team' && tab.view.created_by !== userId && !selected.has(tab.id)
        return (!hidden.has(tab.id) && !unselectedTeamView) || tab.id === activeTabId
    })
}

export function getAccountTabIdFromRoute(routeKey: string): string {
    return routeKey.startsWith('view:') ? routeKey : `system:${routeKey}`
}

export function getAccountTabRoute(tabId: string): string {
    return tabId.startsWith('system:') ? tabId.slice('system:'.length) : tabId
}

export function getDefaultAccountTabId(tabs: AccountTabDefinition[], config: AccountDetailTabsConfigApi): string {
    const tabIds = new Set(tabs.map((tab) => tab.id))
    const hidden = new Set(config.hidden_tab_ids)
    if (config.default_tab_id && tabIds.has(config.default_tab_id) && !hidden.has(config.default_tab_id)) {
        return config.default_tab_id
    }
    return (
        tabs.find((tab) => tab.kind === 'system' && !hidden.has(tab.id))?.id ??
        tabs.find((tab) => tab.kind === 'system')?.id ??
        'system:notes'
    )
}
