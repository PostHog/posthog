import { QuickFilterContext } from '~/queries/schema/schema-general'

export const QuickFiltersEvents = {
    QuickFilterCreated: 'quick filter created',
    QuickFilterUpdated: 'quick filter updated',
    QuickFilterSelected: 'quick filter selected',
    QuickFiltersModalOpened: 'quick filters modal opened',
}

/** Auto-discovered values come only from these events, so a filter offers values its context can match. */
export const QUICK_FILTER_VALUE_EVENT_NAMES: Partial<Record<QuickFilterContext, string[]>> = {
    [QuickFilterContext.ErrorTrackingIssueFilters]: ['$exception'],
}
