import { InspectorListItemPerformance } from 'scenes/session-recordings/apm/performanceEventDataLogic'
import {
    IMAGE_WEB_EXTENSIONS,
    InspectorListBrowserVisibility,
    InspectorListItem,
    InspectorListItemConsole,
    InspectorListItemDoctor,
    InspectorListItemEvent,
    InspectorListOfflineStatusChange,
} from 'scenes/session-recordings/player/inspector/playerInspectorLogic'
import type { SharedListMiniFilter } from 'scenes/session-recordings/player/playerSettingsLogic'

import { SessionRecordingPlayerTab } from '~/types'

const PostHogMobileEvents = [
    'Deep Link Opened',
    'Application Opened',
    'Application Backgrounded',
    'Application Updated',
    'Application Installed',
    'Application Became Active',
]

function isMobileEvent(item: InspectorListItem): boolean {
    return isEvent(item) && PostHogMobileEvents.includes(item.data.event)
}

function isPostHogEvent(item: InspectorListItem): boolean {
    return (isEvent(item) && item.data.event.startsWith('$')) || isMobileEvent(item)
}

function isNetworkEvent(item: InspectorListItem): item is InspectorListItemPerformance {
    return item.type === SessionRecordingPlayerTab.NETWORK
}

function isOfflineStatusChange(item: InspectorListItem): item is InspectorListOfflineStatusChange {
    return item.type === 'offline-status'
}

function isBrowserVisibilityEvent(item: InspectorListItem): item is InspectorListBrowserVisibility {
    return item.type === 'browser-visibility'
}

function isNavigationEvent(item: InspectorListItem): boolean {
    return isNetworkEvent(item) && ['navigation'].includes(item.data.entry_type || '')
}

function isNetworkError(item: InspectorListItem): boolean {
    return isNetworkEvent(item) && (item.data.response_status || -1) >= 400
}

function isSlowNetwork(item: InspectorListItem): boolean {
    return isNetworkEvent(item) && (item.data.duration || -1) >= 1000
}

function isEvent(item: InspectorListItem): item is InspectorListItemEvent {
    return item.type === SessionRecordingPlayerTab.EVENTS
}

function isPageviewOrScreen(item: InspectorListItem): boolean {
    return isEvent(item) && ['$pageview', '$screen'].includes(item.data.event)
}

function isAutocapture(item: InspectorListItem): boolean {
    return isEvent(item) && item.data.event === '$autocapture'
}

function isConsoleEvent(item: InspectorListItem): item is InspectorListItemConsole {
    return item.type === SessionRecordingPlayerTab.CONSOLE
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

export function filterInspectorListItems({
    allItems,
    tab,
    miniFiltersByKey,
    showMatchingEventsFilter,
    showOnlyMatching,
    windowIdFilter,
}: {
    allItems: InspectorListItem[]
    tab: SessionRecordingPlayerTab
    miniFiltersByKey: {
        [key: string]: SharedListMiniFilter
    }
    showMatchingEventsFilter: boolean
    showOnlyMatching: boolean
    windowIdFilter: string | null
}): InspectorListItem[] {
    const items: InspectorListItem[] = []

    const shortCircuitExclude = (item: InspectorListItem): boolean =>
        isNetworkEvent(item) && item.data.entry_type === 'paint'

    const inspectorTabFilters: Record<SessionRecordingPlayerTab, (item: InspectorListItem) => boolean> = {
        [SessionRecordingPlayerTab.ALL]: (item: InspectorListItem) => {
            const isAllEverything = miniFiltersByKey['all-everything']?.enabled === true
            const isAllAutomatic =
                !!miniFiltersByKey['all-automatic']?.enabled &&
                (isOfflineStatusChange(item) ||
                    isBrowserVisibilityEvent(item) ||
                    isNavigationEvent(item) ||
                    isNetworkError(item) ||
                    isSlowNetwork(item) ||
                    isMobileEvent(item) ||
                    isPageviewOrScreen(item) ||
                    isAutocapture(item))
            const isAllErrors =
                (!!miniFiltersByKey['all-errors']?.enabled && isNetworkError(item)) ||
                isConsoleError(item) ||
                isException(item) ||
                isErrorEvent(item)
            return isAllEverything || isAllAutomatic || isAllErrors
        },
        [SessionRecordingPlayerTab.EVENTS]: (item: InspectorListItem) => {
            if (item.type !== SessionRecordingPlayerTab.EVENTS) {
                return false
            }
            return (
                !!miniFiltersByKey['events-all']?.enabled ||
                (!!miniFiltersByKey['events-posthog']?.enabled && isPostHogEvent(item)) ||
                (!!miniFiltersByKey['events-custom']?.enabled && !isPostHogEvent(item)) ||
                (!!miniFiltersByKey['events-pageview']?.enabled &&
                    ['$pageview', '$screen'].includes(item.data.event)) ||
                (!!miniFiltersByKey['events-autocapture']?.enabled && item.data.event === '$autocapture') ||
                (!!miniFiltersByKey['events-exceptions']?.enabled && item.data.event === '$exception')
            )
        },
        [SessionRecordingPlayerTab.CONSOLE]: (item: InspectorListItem) => {
            if (item.type !== SessionRecordingPlayerTab.CONSOLE) {
                return false
            }
            return (
                !!miniFiltersByKey['console-all']?.enabled ||
                (!!miniFiltersByKey['console-info']?.enabled && ['log', 'info'].includes(item.data.level)) ||
                (!!miniFiltersByKey['console-warn']?.enabled && item.data.level === 'warn') ||
                (!!miniFiltersByKey['console-error']?.enabled && isConsoleError(item))
            )
        },
        [SessionRecordingPlayerTab.NETWORK]: (item: InspectorListItem) => {
            if (item.type !== SessionRecordingPlayerTab.NETWORK) {
                return false
            }
            return (
                !!miniFiltersByKey['performance-all']?.enabled === true ||
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
            )
        },
        [SessionRecordingPlayerTab.DOCTOR]: (item: InspectorListItem) => {
            return (
                isOfflineStatusChange(item) ||
                isBrowserVisibilityEvent(item) ||
                isException(item) ||
                isDoctorEvent(item)
            )
        },
    }

    for (const item of allItems) {
        let include = false

        if (shortCircuitExclude(item)) {
            continue
        }

        include = inspectorTabFilters[tab](item)

        if (showMatchingEventsFilter && showOnlyMatching) {
            // Special case - overrides the others
            include = include && item.highlightColor === 'primary'
        }

        const itemWindowId = item.windowId // how do we use sometimes properties $window_id... maybe we just shouldn't need to :shrug:
        const excludedByWindowFilter = !!windowIdFilter && !!itemWindowId && itemWindowId !== windowIdFilter

        if (!include || excludedByWindowFilter) {
            continue
        }

        items.push(item)
    }

    return items
}
