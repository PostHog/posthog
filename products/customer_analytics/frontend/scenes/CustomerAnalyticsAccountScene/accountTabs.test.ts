import type { AccountDetailTabsConfigApi, AccountViewApi } from '../../generated/api.schemas'
import {
    getActiveAccountTabId,
    getDefaultAccountTabId,
    isAccountTabVisible,
    listOrderedAccountTabs,
    listVisibleAccountTabs,
    moveAccountTab,
    setAccountTabVisibility,
    type AccountTabDefinition,
} from './accountTabs'

const emptyConfig: AccountDetailTabsConfigApi = {
    ordered_tab_ids: [],
    hidden_tab_ids: [],
    default_tab_id: null,
}

const tabs: AccountTabDefinition[] = [
    { id: 'system:notes', routeKey: 'notes', label: 'Notes', kind: 'system', systemKind: 'notes' },
    { id: 'system:users', routeKey: 'users', label: 'Users', kind: 'system', systemKind: 'users' },
    {
        id: 'view:shared',
        routeKey: 'view:shared',
        label: 'Shared view',
        kind: 'view',
        view: { id: 'shared', name: 'Shared view', visibility: 'team', created_by: 2 } as AccountViewApi,
    },
]

describe('account tabs', () => {
    it('falls back from an unavailable system route but keeps an unknown view route', () => {
        expect(getActiveAccountTabId(tabs, emptyConfig, 'system:tasks')).toBe('system:notes')
        expect(getActiveAccountTabId(tabs, emptyConfig, 'view:missing')).toBe('view:missing')
    })

    it('does not apply system tab preferences while the tab settings flag is disabled', () => {
        const config: AccountDetailTabsConfigApi = {
            ordered_tab_ids: ['system:users'],
            hidden_tab_ids: ['system:notes'],
            default_tab_id: 'system:users',
        }

        expect(listOrderedAccountTabs(tabs, config, false).map((tab) => tab.id)).toEqual([
            'system:notes',
            'system:users',
            'view:shared',
        ])
        expect(listVisibleAccountTabs(tabs, config, undefined, 1, false).map((tab) => tab.id)).toEqual([
            'system:notes',
            'system:users',
        ])
        expect(getDefaultAccountTabId(tabs, config, false)).toBe('system:notes')
        expect(getDefaultAccountTabId(tabs, config, true)).toBe('system:users')
    })

    it('does not opt into another user’s team view while reordering system tabs', () => {
        const config = moveAccountTab(tabs, emptyConfig, 1, 'system:users', 'up')

        expect(config.ordered_tab_ids).toEqual(['system:users', 'system:notes'])
        expect(config.ordered_tab_ids).not.toContain('view:shared')
        expect(isAccountTabVisible(tabs[2], config, 1)).toBe(false)
    })

    it('places a newly selected team view after the existing tabs', () => {
        const config = setAccountTabVisibility(tabs, tabs[2], emptyConfig, 1, true)

        expect(config.ordered_tab_ids).toEqual(['system:notes', 'system:users', 'view:shared'])
        expect(listVisibleAccountTabs(tabs, config, undefined, 1).map((tab) => tab.id)).toEqual([
            'system:notes',
            'system:users',
            'view:shared',
        ])
    })
})
