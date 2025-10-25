import { InspectorListItemPerformance } from 'scenes/session-recordings/apm/performanceEventDataLogic'
import { MiniFilterKey, SharedListMiniFilter } from 'scenes/session-recordings/player/inspector/miniFiltersLogic'
import {
    IMAGE_WEB_EXTENSIONS,
    InspectorListItem,
    InspectorListItemConsole,
    InspectorListItemDoctor,
    InspectorListItemEvent,
} from 'scenes/session-recordings/player/inspector/playerInspectorLogic'

const PostHogMobileEvents = [
    'Deep Link Opened',
    'Application Opened',
    'Application Backgrounded',
    'Application Updated',
    'Application Installed',
    'Application Became Active',
]

function isPostHogMobileEvent(item: InspectorListItem): boolean {
    return isEvent(item) && PostHogMobileEvents.includes(item.data.event)
}

function isPostHogEvent(item: InspectorListItem): boolean {
    return (isEvent(item) && item.data.event.startsWith('$')) || isPostHogMobileEvent(item)
}

function isNetworkEvent(item: InspectorListItem): item is InspectorListItemPerformance {
    return item.type === 'network'
}

function isNavigationEvent(item: InspectorListItem): boolean {
    return isNetworkEvent(item) && ['navigation'].includes(item.data.entry_type || '')
}

function isEvent(item: InspectorListItem): item is InspectorListItemEvent {
    return item.type === 'events'
}

function isPageviewOrScreen(item: InspectorListItem): boolean {
    return isEvent(item) && ['$pageview', '$screen'].includes(item.data.event)
}

function isAutocapture(item: InspectorListItem): boolean {
    return isEvent(item) && item.data.event === '$autocapture'
}

function isConsoleEvent(item: InspectorListItem): item is InspectorListItemConsole {
    return item.type === 'console'
}

function isConsoleError(item: InspectorListItem): boolean {
    return isConsoleEvent(item) && item.data.level === 'error'
}

function isException(item: InspectorListItem): boolean {
    return isEvent(item) && item.data.event === '$exception'
}

function isErrorEvent(item: InspectorListItem): boolean {
    return isEvent(item) && item.data.event.toLowerCase().includes('error')
}

function isDoctorEvent(item: InspectorListItem): item is InspectorListItemDoctor {
    return item.type === 'doctor'
}

function isContextItem(item: InspectorListItem): boolean {
    return ['browser-visibility', 'offline-status', 'inspector-summary', 'inactivity'].includes(item.type)
}

const eventsMatch = (
    item: InspectorListItemEvent,
    miniFiltersByKey: { [p: MiniFilterKey]: SharedListMiniFilter }
): SharedListMiniFilter | null => {
    if (isException(item) || isErrorEvent(item)) {
        return miniFiltersByKey['events-exceptions']
    } else if (isAutocapture(item)) {
        return miniFiltersByKey['events-autocapture']
    } else if (isPageviewOrScreen(item)) {
        return miniFiltersByKey['events-pageview']
    } else if (isPostHogEvent(item)) {
        return miniFiltersByKey['events-posthog']
    } else if (!isPostHogEvent(item)) {
        return miniFiltersByKey['events-custom']
    }
    return null
}

const consoleMatch = (
    item: InspectorListItemConsole,
    miniFiltersByKey: { [p: MiniFilterKey]: SharedListMiniFilter }
): SharedListMiniFilter | null => {
    if (['log', 'info'].includes(item.data.level)) {
        return miniFiltersByKey['console-info']
    } else if (item.data.level === 'warn') {
        return miniFiltersByKey['console-warn']
    } else if (isConsoleError(item)) {
        return miniFiltersByKey['console-error']
    }
    return null
}

function networkMatch(
    item: InspectorListItemPerformance,
    miniFiltersByKey: {
        [p: MiniFilterKey]: SharedListMiniFilter
    }
): SharedListMiniFilter | null {
    if (isNavigationEvent(item)) {
        return miniFiltersByKey['performance-document']
    } else if (['fetch', 'xmlhttprequest'].includes(item.data.initiator_type || '')) {
        return miniFiltersByKey['performance-fetch']
    } else if (
        item.data.initiator_type === 'script' ||
        (['link', 'other'].includes(item.data.initiator_type || '') && item.data.name?.includes('.js'))
    ) {
        return miniFiltersByKey['performance-assets-js']
    } else if (
        item.data.initiator_type === 'css' ||
        (['link', 'other'].includes(item.data.initiator_type || '') && item.data.name?.includes('.css'))
    ) {
        return miniFiltersByKey['performance-assets-css']
    } else if (
        item.data.initiator_type === 'img' ||
        (['link', 'other'].includes(item.data.initiator_type || '') &&
            !!IMAGE_WEB_EXTENSIONS.some((ext) => item.data.name?.includes(`.${ext}`)))
    ) {
        return miniFiltersByKey['performance-assets-img']
    } else if (
        ['other'].includes(item.data.initiator_type || '') &&
        ![...IMAGE_WEB_EXTENSIONS, 'css', 'js'].some((ext) => item.data.name?.includes(`.${ext}`))
    ) {
        return miniFiltersByKey['performance-other']
    }
    return null
}

export function itemToMiniFilter(
    item: InspectorListItem,
    miniFiltersByKey: { [p: MiniFilterKey]: SharedListMiniFilter }
): SharedListMiniFilter | null {
    switch (item.type) {
        case 'events':
            return eventsMatch(item, miniFiltersByKey)
        case 'console':
            return consoleMatch(item, miniFiltersByKey)
        case 'network':
            return networkMatch(item, miniFiltersByKey)
        case 'comment':
            return item.type === 'comment' ? miniFiltersByKey['comment'] : null
        case 'app-state':
            return item.type === 'app-state' ? miniFiltersByKey['console-app-state'] : null
        case 'doctor':
            if (isDoctorEvent(item)) {
                return miniFiltersByKey['doctor']
            }
            break
    }
    return null
}

export function filterInspectorListItems({
    allItems,
    miniFiltersByKey,
    allowMatchingEventsFilter,
    showOnlyMatching,
    trackedWindow,
    hasEventsToDisplay,
}: {
    allItems: InspectorListItem[]
    miniFiltersByKey:
        | {
              [key: MiniFilterKey]: SharedListMiniFilter
          }
        | undefined
    allowMatchingEventsFilter: boolean
    showOnlyMatching: boolean
    trackedWindow: string | null
    hasEventsToDisplay: boolean
}): InspectorListItem[] {
    const items: InspectorListItem[] = []

    const shortCircuitExclude = (item: InspectorListItem): boolean =>
        isNetworkEvent(item) && item.data.entry_type === 'paint'

    if (!miniFiltersByKey) {
        return []
    }

    for (const item of allItems) {
        let include = false

        if (shortCircuitExclude(item)) {
            continue
        }

        const itemFilter = itemToMiniFilter(item, miniFiltersByKey)
        include = isContextItem(item) || !!itemFilter?.enabled

        if (allowMatchingEventsFilter && showOnlyMatching && hasEventsToDisplay) {
            // Special case - overrides the others
            include = include && item.highlightColor === 'primary'
        }

        const itemWindowId = item.windowId // how do we use sometimes properties $window_id... maybe we just shouldn't need to :shrug:
        const excludedByWindowFilter = !!trackedWindow && !!itemWindowId && itemWindowId !== trackedWindow

        if (!include || excludedByWindowFilter) {
            continue
        }

        items.push(item)
    }

    return items.every((i) => isContextItem(i)) ? [] : items
}
