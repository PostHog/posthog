import type { AccountsOverviewTile } from './accountsOverviewTilesLogic'

// PostHog's Salesforce instance origin; append a record id to deep-link to that record (account or opportunity).
export const SALESFORCE_ORIGIN = 'https://posthog.my.salesforce.com'

export const ACCOUNTS_OVERVIEW_THRESHOLD_OPERATORS = ['>', '>=', '<', '<=', '=', '!='] as const
export type AccountsOverviewThresholdOperator = (typeof ACCOUNTS_OVERVIEW_THRESHOLD_OPERATORS)[number]

export const NUMERIC_FIELD_TYPES = new Set(['integer', 'float', 'decimal'])

export const MAX_ACCOUNTS_OVERVIEW_TILES = 5

export const DEFAULT_TILES: AccountsOverviewTile[] = [
    { id: 'default-accounts', label: 'Accounts', metric: { type: 'count' } },
]

// Overview tiles used to be persisted per-team in localStorage; they now live in saved views
// (`properties.tiles`). We no longer WRITE this key — `accountsOverviewTilesLogic` only reads any
// pre-existing value once on mount (to seed the working state) and emits an
// `OverviewTilesLocalStorageRead` tombstone. Once that event stops firing, no browser still carries
// a legacy value and this read path (plus the prefix) can be deleted.
const overviewTilesTeamId = window.POSTHOG_APP_CONTEXT?.current_team?.id
export const ACCOUNTS_OVERVIEW_LEGACY_TILES_PREFIX = `${overviewTilesTeamId}_customer_analytics_accounts_overview__`

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
    OverviewTilesLocalStorageRead: 'customer analytics accounts overview tiles localstorage read',
    ViewSaved: 'customer analytics accounts view saved',
    ViewUpdated: 'customer analytics accounts view updated',
    ViewSelected: 'customer analytics accounts view selected',
    ViewDeleted: 'customer analytics accounts view deleted',
    RoleAssigned: 'customer analytics account role assigned',
    LinkClicked: 'customer analytics account link clicked',
    NoteClicked: 'customer analytics account note clicked',
    NoteCreated: 'customer analytics accounts note created',
    NotesSearched: 'customer analytics accounts notes searched',
    NotesSorted: 'customer analytics accounts notes sorted',
    TabViewed: 'customer analytics account tab viewed',
    RelatedUserClicked: 'customer analytics account related user clicked',
    OpportunityClicked: 'customer analytics account opportunity clicked',
} as const
