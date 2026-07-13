import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import type { accountsExpansionLogicType } from './accountsExpansionLogicType'
import { AccountsEvents } from './constants'

export type AccountExpansionTab = 'notes' | 'users' | 'relationships' | 'usage' | 'spend' | 'opportunities'

export const ACCOUNT_EXPANSION_TABS: AccountExpansionTab[] = [
    'notes',
    'users',
    'relationships',
    'usage',
    'spend',
    'opportunities',
]

export const DEFAULT_ACCOUNT_TAB: AccountExpansionTab = 'notes'

export const accountsExpansionLogic = kea<accountsExpansionLogicType>([
    path(['scenes', 'customerAnalytics', 'accounts', 'accountsExpansionLogic']),
    actions({
        toggleAccountExpanded: (accountId: string) => ({ accountId }),
        setActiveTab: (accountId: string, tab: AccountExpansionTab) => ({ accountId, tab }),
        openAccountTab: (accountId: string, tab: AccountExpansionTab) => ({ accountId, tab }),
    }),
    reducers({
        expandedAccountIds: [
            [] as string[],
            {
                toggleAccountExpanded: (state, { accountId }) =>
                    state.includes(accountId) ? state.filter((id) => id !== accountId) : [...state, accountId],
                openAccountTab: (state, { accountId }) => (state.includes(accountId) ? state : [...state, accountId]),
            },
        ],
        activeTabByAccount: [
            {} as Record<string, AccountExpansionTab>,
            {
                setActiveTab: (state, { accountId, tab }) => ({ ...state, [accountId]: tab }),
                openAccountTab: (state, { accountId, tab }) => ({ ...state, [accountId]: tab }),
            },
        ],
    }),
    selectors({
        isAccountExpanded: [
            (s) => [s.expandedAccountIds],
            (expandedAccountIds) =>
                (accountId: string): boolean =>
                    expandedAccountIds.includes(accountId),
        ],
        activeTabFor: [
            (s) => [s.activeTabByAccount],
            (activeTabByAccount) =>
                (accountId: string): AccountExpansionTab =>
                    activeTabByAccount[accountId] ?? DEFAULT_ACCOUNT_TAB,
        ],
    }),
    listeners({
        // Only genuine user tab clicks report engagement. Programmatic navigation
        // (openAccountTab) deliberately does not, to avoid phantom events.
        setActiveTab: ({ tab }) => {
            posthog.capture(AccountsEvents.TabViewed, { tab })
        },
    }),
])
