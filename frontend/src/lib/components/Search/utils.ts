import { Dayjs, dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils'

export const getCategoryDisplayName = (category: string): string => {
    const displayNames: Record<string, string> = {
        'create-new': 'Create new',
        apps: 'Apps',
        'data-management': 'Data management',
        early_access_feature: 'Early access features',
        recents: 'Recents',
        folders: 'Folders',
        persons: 'Persons',
        groups: 'Groups',
        eventDefinitions: 'Events',
        propertyDefinitions: 'Properties',
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
