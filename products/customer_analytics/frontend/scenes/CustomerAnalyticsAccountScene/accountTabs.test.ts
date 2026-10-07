import type { AccountDetailTabsConfigApi, AccountViewApi } from '../../generated/api.schemas'
import {
    getActiveAccountTabId,
    getDefaultAccountTabId,
    isAccountTabVisible,
    listAccountTabs,
    listOrderedAccountTabs,
    listVisibleAccountTabs,
    reorderAccountTab,
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
    it('does not add a system tab for the properties widget', () => {
        expect(listAccountTabs({}, []).map(({ id }) => id)).not.toContain('system:properties')
    })

    it('falls back from an unavailable system route but keeps an unknown view route', () => {
        expect(getActiveAccountTabId(tabs, emptyConfig, 'system:tasks', 1)).toBe('system:notes')
        expect(getActiveAccountTabId(tabs, emptyConfig, 'view:missing', 1)).toBe('view:missing')
    })

    it('does not apply tab preferences while account views are disabled', () => {
        const config: AccountDetailTabsConfigApi = {
            ordered_tab_ids: ['system:users'],
            hidden_tab_ids: ['system:notes', 'view:shared'],
            default_tab_id: 'system:users',
        }

        expect(listOrderedAccountTabs(tabs, config, false).map((tab) => tab.id)).toEqual([
            'view:shared',
            'system:notes',
            'system:users',
        ])
        expect(listVisibleAccountTabs(tabs, config, undefined, 1, false).map((tab) => tab.id)).toEqual([
            'view:shared',
            'system:notes',
            'system:users',
        ])
        expect(getDefaultAccountTabId(tabs, config, 1, false)).toBe('system:notes')
        expect(getDefaultAccountTabId(tabs, config, 1, true)).toBe('system:users')
    })

    it('does not opt into another user’s team view while reordering system tabs', () => {
        const config = reorderAccountTab(tabs, emptyConfig, 1, 'system:users', 'system:notes')

        expect(config.ordered_tab_ids).toEqual(['system:users', 'system:notes'])
        expect(config.ordered_tab_ids).not.toContain('view:shared')
        expect(isAccountTabVisible(tabs[2], config, 1)).toBe(false)
    })

    it('lists a newly selected team view with the views, ahead of system tabs', () => {
        const config = setAccountTabVisibility(tabs, tabs[2], emptyConfig, 1, true)

        expect(config.ordered_tab_ids).toEqual(['system:notes', 'system:users', 'view:shared'])
        expect(listVisibleAccountTabs(tabs, config, undefined, 1).map((tab) => tab.id)).toEqual([
            'view:shared',
            'system:notes',
            'system:users',
        ])
    })

    it('defaults to a visible view before a hidden system tab', () => {
        const config = setAccountTabVisibility(tabs, tabs[2], emptyConfig, 1, true)
        const allSystemTabsHidden = { ...config, hidden_tab_ids: ['system:notes', 'system:users'] }

        expect(getDefaultAccountTabId(tabs, allSystemTabsHidden, 1)).toBe('view:shared')
        expect(getDefaultAccountTabId(tabs, { ...allSystemTabsHidden, ordered_tab_ids: [] }, 1)).toBe('system:notes')
    })
})
