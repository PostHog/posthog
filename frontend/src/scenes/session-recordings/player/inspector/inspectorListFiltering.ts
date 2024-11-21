import { InspectorListItemPerformance } from 'scenes/session-recordings/apm/performanceEventDataLogic'
import { MiniFilterKey, SharedListMiniFilter } from 'scenes/session-recordings/player/inspector/miniFiltersLogic'
import {
    IMAGE_WEB_EXTENSIONS,
    InspectorListItem,
    InspectorListItemConsole,
    InspectorListItemDoctor,
    InspectorListItemEvent,
} from 'scenes/session-recordings/player/inspector/playerInspectorLogic'

import { InspectorListItemType } from '~/types'

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
    return item.type === InspectorListItemType.NETWORK
}
//
// function isOfflineStatusChange(item: InspectorListItem): item is InspectorListOfflineStatusChange {
//     return item.type === 'offline-status'
// }
//
// function isBrowserVisibilityEvent(item: InspectorListItem): item is InspectorListBrowserVisibility {
//     return item.type === 'browser-visibility'
// }

function isNavigationEvent(item: InspectorListItem): boolean {
    return isNetworkEvent(item) && ['navigation'].includes(item.data.entry_type || '')
}
//
// function isNetworkError(item: InspectorListItem): boolean {
//     return isNetworkEvent(item) && (item.data.response_status || -1) >= 400
// }

function isEvent(item: InspectorListItem): item is InspectorListItemEvent {
    return item.type === InspectorListItemType.EVENTS
}

function isPageviewOrScreen(item: InspectorListItem): boolean {
    return isEvent(item) && ['$pageview', '$screen'].includes(item.data.event)
}

function isAutocapture(item: InspectorListItem): boolean {
    return isEvent(item) && item.data.event === '$autocapture'
}

function isConsoleEvent(item: InspectorListItem): item is InspectorListItemConsole {
    return item.type === InspectorListItemType.CONSOLE
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
//
// function isComment(item: InspectorListItem): item is InspectorListItemComment {
//     return item.type === 'comment'
// }

function isContextItem(item: InspectorListItem): boolean {
    return ['browser-visibility', 'offline-status', 'comment'].includes(item.type)
}

export function filterInspectorListItems({
    allItems,
    miniFiltersByKey,
    showMatchingEventsFilter,
    showOnlyMatching,
    trackedWindow,
}: {
    allItems: InspectorListItem[]
    miniFiltersByKey:
        | {
              [key: MiniFilterKey]: SharedListMiniFilter
          }
        | undefined
    showMatchingEventsFilter: boolean
    showOnlyMatching: boolean
    trackedWindow: string | null
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

        if (isContextItem(item)) {
            include = true
        }

        if (item.type === InspectorListItemType.EVENTS) {
            include =
                (!!miniFiltersByKey['events-posthog']?.enabled && isPostHogEvent(item)) ||
                (!!miniFiltersByKey['events-custom']?.enabled && !isPostHogEvent(item)) ||
                (!!miniFiltersByKey['events-pageview']?.enabled && isPageviewOrScreen(item)) ||
                (!!miniFiltersByKey['events-autocapture']?.enabled && isAutocapture(item)) ||
                (!!miniFiltersByKey['events-exceptions']?.enabled && (isException(item) || isErrorEvent(item)))
        }

        if (item.type === InspectorListItemType.CONSOLE) {
            include =
                (!!miniFiltersByKey['console-info']?.enabled && ['log', 'info'].includes(item.data.level)) ||
                (!!miniFiltersByKey['console-warn']?.enabled && item.data.level === 'warn') ||
                (!!miniFiltersByKey['console-error']?.enabled && isConsoleError(item))
        }

        if (item.type === InspectorListItemType.NETWORK) {
            include =
                (!!miniFiltersByKey['performance-document']?.enabled && isNavigationEvent(item)) ||
                (!!miniFiltersByKey['performance-fetch']?.enabled &&
                    item.data.entry_type === 'resource' &&
                    ['fetch', 'xmlhttprequest'].includes(item.data.initiator_type || '')) ||
                (!!miniFiltersByKey['performance-assets-js']?.enabled &&
                    item.data.entry_type === 'resource' &&
                    (item.data.initiator_type === 'script' ||
                        (['link', 'other'].includes(item.data.initiator_type || '') &&
                            item.data.name?.includes('.js')))) ||
                (!!miniFiltersByKey['performance-assets-css']?.enabled &&
                    item.data.entry_type === 'resource' &&
                    (item.data.initiator_type === 'css' ||
                        (['link', 'other'].includes(item.data.initiator_type || '') &&
                            item.data.name?.includes('.css')))) ||
                (!!miniFiltersByKey['performance-assets-img']?.enabled &&
                    item.data.entry_type === 'resource' &&
                    (item.data.initiator_type === 'img' ||
                        (['link', 'other'].includes(item.data.initiator_type || '') &&
                            !!IMAGE_WEB_EXTENSIONS.some((ext) => item.data.name?.includes(`.${ext}`))))) ||
                (!!miniFiltersByKey['performance-other']?.enabled &&
                    item.data.entry_type === 'resource' &&
                    ['other'].includes(item.data.initiator_type || '') &&
                    ![...IMAGE_WEB_EXTENSIONS, 'css', 'js'].some((ext) => item.data.name?.includes(`.${ext}`)))
        }

        if (item.type === InspectorListItemType.DOCTOR) {
            include = !!miniFiltersByKey['doctor']?.enabled && isDoctorEvent(item)
        }

        // what about isOfflineStatusChange(item) || isBrowserVisibilityEvent(item) || isComment(item)

        if (showMatchingEventsFilter && showOnlyMatching) {
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
