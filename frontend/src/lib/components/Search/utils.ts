import { Dayjs, dayjs } from 'lib/dayjs'
import { FuseResultMatch, createFuse } from 'lib/utils/fuseSearch'
import { PLACEHOLDER_HREF } from 'lib/utils/navigateToHref'
import { pluralize } from 'lib/utils/strings'

/** Synthetic result that jumps to the theme setting, or toggles the theme outright. */
export const SETTINGS_THEME_ITEM_ID = '__settings_theme__'

interface FuseSearchable {
    name: string
    displayName?: string
    category: string
    searchKeywords?: string[]
    hiddenSearchText?: string
    matchedSearchKeyword?: string | null
}

export const SEARCH_TAB_CATEGORY = 'tabs'
const SEARCH_KEYWORDS_KEY = 'searchKeywords'
const NAME_KEYS = new Set(['name', 'displayName'])

const FUSE_OPTIONS = {
    keys: [
        { name: 'name', weight: 2 },
        { name: 'displayName', weight: 2 },
        {
            name: 'category',
            weight: 0.5,
            getFn: (item: FuseSearchable): string => (item.category === SEARCH_TAB_CATEGORY ? '' : item.category),
        },
        { name: SEARCH_KEYWORDS_KEY, weight: 1.5 },
        { name: 'hiddenSearchText', weight: 1 },
    ],
    ignoreLocation: true,
    useExtendedSearch: true,
    includeMatches: true,
}

const keywordOnlyMatch = (matches: readonly FuseResultMatch[] = []): string | null => {
    if (matches.some((match) => match.key && NAME_KEYS.has(match.key))) {
        return null
    }
    return matches.find((match) => match.key === SEARCH_KEYWORDS_KEY)?.value ?? null
}

// Lists come from memoized selectors, so the same array reaches here on every keystroke.
// Building the index once per array keeps typing to a search, not a rebuild.
const fuseByItems = new WeakMap<FuseSearchable[], ReturnType<typeof createFuse<FuseSearchable>>>()

/**
 * Filter items using Fuse.js fuzzy search. Searches across name, displayName,
 * category, and searchKeywords with weighted scoring.
 */

export function filterSearchItems<T extends FuseSearchable>(items: T[], query: string): T[] {
    const trimmed = query.trim()
    if (!trimmed) {
        return items
    }
    let fuse = fuseByItems.get(items)
    if (!fuse) {
        fuse = createFuse<FuseSearchable>(items, FUSE_OPTIONS)
        fuseByItems.set(items, fuse)
    }
    return fuse.search(trimmed).map((result) => ({
        ...(result.item as T),
        matchedSearchKeyword: keywordOnlyMatch(result.matches),
    }))
}

/** Structural so this module avoids importing searchLogic, which imports this one. */
interface NewTabCandidate {
    id: string
    href?: string
    onSelect?: () => void
}

/**
 * Whether Cmd/Ctrl activation should open an item in a new tab. Only items that purely
 * navigate qualify. An item carrying `onSelect`, and the theme row, run an action instead,
 * so treating the modifier as "open in a new tab" would fire that action rather than open
 * anything, which is merely surprising for most items but destructive for "Log out".
 * A placeholder href goes nowhere, so it would open an empty tab.
 */
export const canOpenInNewTab = (item: NewTabCandidate): boolean =>
    !!item.href && item.href !== PLACEHOLDER_HREF && !item.onSelect && item.id !== SETTINGS_THEME_ITEM_ID

/** Optional leading `#` and nothing but digits — the shape the ticket endpoint resolves with an
 *  exact ticket-number lookup rather than a text scan (`is_ticket_number_search` server-side). */
const TICKET_NUMBER_QUERY = /^#?\d+$/

/** Below this, a free-text ticket search is not worth sending. */
const TICKET_SEARCH_MIN_LENGTH = 3

/** The ticket endpoint drops a `search` longer than this rather than rejecting it
 *  (`MAX_SEARCH_LENGTH` in products/conversations/backend/api/ticket_filters.py), and would answer
 *  an over-long query with unfiltered tickets — rows presented as matches that match nothing. */
const TICKET_SEARCH_MAX_LENGTH = 200

/**
 * Whether a query is worth sending to the ticket endpoint. Free-text ticket search scans message
 * content, which is the most expensive lookup in the palette, and one or two characters match most
 * of a support inbox anyway. A ticket number is exempt from the lower bound in both directions: it
 * is an indexed lookup, and "#7" is a complete query rather than the start of a longer one.
 */
export const shouldSearchTickets = (query: string): boolean => {
    const trimmed = query.trim()
    if (trimmed.length > TICKET_SEARCH_MAX_LENGTH) {
        return false
    }
    return trimmed.length >= TICKET_SEARCH_MIN_LENGTH || TICKET_NUMBER_QUERY.test(trimmed)
}

export const getCategoryDisplayName = (category: string): string => {
    const displayNames: Record<string, string> = {
        create: 'Create new',
        'create-new': 'Create new',
        tools: 'Products',
        'data-management': 'Data management',
        [SEARCH_TAB_CATEGORY]: 'Tabs',
        settings: 'Settings',
        early_access_feature: 'Early access features',
        suggested: 'Suggested',
        recents: 'Recents',
        starred: 'Starred',
        folders: 'Folders',
        persons: 'Persons',
        groups: 'Groups',
        accounts: 'Accounts',
        tickets: 'Support tickets',
        eventDefinitions: 'Events',
        propertyDefinitions: 'Properties',
        ai: 'PostHog AI',
        askAI: 'Posthog AI',
        insight: 'Insights',
        dashboard: 'Dashboards',
        feature_flag: 'Feature flags',
        experiment: 'Experiments',
        survey: 'Surveys',
        notebook: 'Notebooks',
        cohort: 'Cohorts',
        action: 'Actions',
        event_definition: 'Event definitions',
        property_definition: 'Property definitions',
        session_recording_playlist: 'Session recording filter',
        hog_flow: 'Workflows',
        health: 'Health',
        misc: 'Misc',
    }

    return displayNames[category] || category
}

export const formatRelativeTimeShort = (date: string | number | Date | Dayjs | null | undefined): string => {
    if (!date) {
        return ''
    }

    const parsedDate = dayjs(date)

    if (!parsedDate.isValid()) {
        return ''
    }

    const now = dayjs()
    const seconds = Math.max(0, now.diff(parsedDate, 'second'))

    if (seconds < 60) {
        return 'just now'
    }

    const minutes = now.diff(parsedDate, 'minute')

    if (minutes < 60) {
        return `${minutes} min ago`
    }

    const hours = now.diff(parsedDate, 'hour')

    if (hours < 24) {
        return `${pluralize(hours, 'hr')} ago`
    }

    const days = now.diff(parsedDate, 'day')

    if (days < 30) {
        return `${pluralize(days, 'day')} ago`
    }

    const months = now.diff(parsedDate, 'month') || 1

    if (months < 12) {
        return `${pluralize(months, 'mo')} ago`
    }

    const years = now.diff(parsedDate, 'year') || 1

    return `${pluralize(years, 'yr')} ago`
}
