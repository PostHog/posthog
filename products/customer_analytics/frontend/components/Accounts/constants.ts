import type { AccountsOverviewTile } from './accountsOverviewTilesLogic'

export const ACCOUNTS_OVERVIEW_THRESHOLD_OPERATORS = ['>', '>=', '<', '<=', '=', '!='] as const
export type AccountsOverviewThresholdOperator = (typeof ACCOUNTS_OVERVIEW_THRESHOLD_OPERATORS)[number]

export const NUMERIC_FIELD_TYPES = new Set(['integer', 'float', 'decimal'])

export const MAX_ACCOUNTS_OVERVIEW_TILES = 5

export const DEFAULT_TILES: AccountsOverviewTile[] = [
    { id: 'default-accounts', label: 'Accounts', metric: { type: 'count' } },
]

const teamIdForPersistence = window.POSTHOG_APP_CONTEXT?.current_team?.id
export const ACCOUNTS_OVERVIEW_PERSIST_CONFIG = {
    persist: true,
    prefix: `${teamIdForPersistence}_customer_analytics_accounts_overview__`,
}
