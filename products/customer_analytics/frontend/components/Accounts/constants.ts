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

// Canonical analytics event names for the accounts list. Every `posthog.capture`
// in this directory must reference these — a mistyped string silently forks a new
// event in PostHog and breaks reporting without any error. Keep in sync with the
// analytics table in AGENTS.md.
export const AccountsEvents = {
    ListViewed: 'customer analytics accounts list viewed',
    FilterChanged: 'customer analytics accounts filter changed',
    Searched: 'customer analytics accounts searched',
    Refreshed: 'customer analytics accounts refreshed',
    Sorted: 'customer analytics accounts sorted',
    ColumnsSaved: 'customer analytics accounts columns saved',
    OverviewTilesEdited: 'customer analytics accounts overview tiles edited',
    ViewSaved: 'customer analytics accounts view saved',
    ViewUpdated: 'customer analytics accounts view updated',
    ViewSelected: 'customer analytics accounts view selected',
    ViewDeleted: 'customer analytics accounts view deleted',
    RoleAssigned: 'customer analytics account role assigned',
    LinkClicked: 'customer analytics account link clicked',
    NoteClicked: 'customer analytics account note clicked',
    TabViewed: 'customer analytics account tab viewed',
    RelatedUserClicked: 'customer analytics account related user clicked',
} as const
