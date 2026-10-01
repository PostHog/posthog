import { QuickFilterContext } from '~/queries/schema/schema-general'

export const QuickFiltersEvents = {
    QuickFilterCreated: 'quick filter created',
    QuickFilterUpdated: 'quick filter updated',
    QuickFilterSelected: 'quick filter selected',
    QuickFiltersModalOpened: 'quick filters modal opened',
}

/**
 * Event names sent with the values lookup for each context.
 * Only a scan of the events table applies them. Values read from the precomputed
 * property values table come from all events, because that table has no event column.
 */
export const QUICK_FILTER_VALUE_EVENT_NAMES: Partial<Record<QuickFilterContext, string[]>> = {
    [QuickFilterContext.ErrorTrackingIssueFilters]: ['$exception'],
}
