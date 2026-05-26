import { dayjs } from 'lib/dayjs'
import { InspectorListItemPerformance } from 'scenes/session-recordings/apm/performanceEventDataLogic'

import { SharedListMiniFilter } from './miniFiltersLogic'
import {
    buildInspectorExportDocument,
    buildInspectorExportItem,
    formatInspectorExportDocumentForClipboard,
} from './playerInspectorExport'
import {
    DisplayGroup,
    InspectorListBrowserVisibility,
    InspectorListItem,
    InspectorListItemAppState,
    InspectorListItemComment,
    InspectorListItemConsole,
    InspectorListItemDoctor,
    InspectorListItemEvent,
    InspectorListItemInactivity,
    InspectorListItemLog,
    InspectorListItemNotebookComment,
    InspectorListItemSummary,
    InspectorListOfflineStatusChange,
    InspectorListSessionChange,
} from './playerInspectorLogic'

const timestamp = dayjs('2024-01-01T00:00:05Z')

function baseItem(overrides: Partial<InspectorListItem> = {}): Omit<InspectorListItemEvent, 'type' | 'data'> {
    return {
        timestamp,
        timeInRecording: 5000,
        search: 'search text',
        key: 'base-key',
        windowId: 1,
        windowNumber: 1,
        ...overrides,
    }
}

function buildDocument(
    items: InspectorListItem[],
    displayGroups?: DisplayGroup[]
): ReturnType<typeof buildInspectorExportDocument> {
    const miniFilters: SharedListMiniFilter[] = [
        { type: 'events', key: 'events-pageview', name: 'Pageview', enabled: true },
        { type: 'console', key: 'console-error', name: 'Error', enabled: false },
    ]

    return buildInspectorExportDocument({
        sessionRecordingId: 'recording-1',
        exportedAt: '2024-01-01T00:00:10Z',
        items,
        displayGroups: displayGroups ?? items.map((_, index) => ({ indices: [index] })),
        searchQuery: 'checkout',
        miniFilters,
        showOnlyMatching: true,
        groupRepeatedItems: true,
        trackedWindow: 1,
        logsHasMore: true,
    })
}

describe('playerInspectorExport', () => {
    it.each([
        [
            'events',
            {
                ...baseItem(),
                type: 'events',
                data: {
                    id: 'event-1',
                    event: '$pageview',
                    distinct_id: 'user-1',
                    properties: { $current_url: 'https://example.com/pricing' },
                    elements: [],
                    timestamp: timestamp.toISOString(),
                    fullyLoaded: true,
                    playerTime: 0,
                },
            } satisfies InspectorListItemEvent,
            { event: '$pageview', event_id: 'event-1', distinct_id: 'user-1' },
        ],
        [
            'console',
            {
                ...baseItem(),
                type: 'console',
                data: {
                    timestamp: timestamp.valueOf(),
                    windowId: 1,
                    level: 'error',
                    content: 'Failed to fetch',
                    lines: ['Failed to fetch'],
                    trace: ['trace line'],
                    count: 2,
                },
            } satisfies InspectorListItemConsole,
            { level: 'error', content: 'Failed to fetch', repeat_count: 2 },
        ],
        [
            'network',
            {
                ...baseItem(),
                type: 'network',
                data: {
                    uuid: 'network-1',
                    timestamp: timestamp.valueOf(),
                    distinct_id: 'user-1',
                    session_id: 'recording-1',
                    window_id: 'window-1',
                    pageview_id: 'pageview-1',
                    current_url: 'https://example.com',
                    entry_type: 'resource',
                    name: 'https://example.com/api',
                    method: 'POST',
                    response_status: 500,
                    duration: 321,
                    request_body: '{"ok":false}',
                },
            } satisfies InspectorListItemPerformance,
            { method: 'POST', response_status: 500, request_body: '{"ok":false}' },
        ],
        [
            'comment',
            {
                ...baseItem(),
                type: 'comment',
                source: 'comment',
                data: {
                    id: 'comment-1',
                    content: 'Needs investigation',
                    rich_content: null,
                    version: 1,
                    created_at: timestamp.toISOString(),
                    created_by: {
                        id: 7,
                        uuid: 'user-uuid',
                        distinct_id: 'user-distinct',
                        email: 'user@example.com',
                        first_name: 'User',
                        last_name: '',
                    },
                    scope: 'recording',
                    item_context: null,
                    is_task: false,
                    completed_at: null,
                    completed_by: null,
                },
            } satisfies InspectorListItemComment,
            { source: 'comment', content: 'Needs investigation' },
        ],
        [
            'notebook comment',
            {
                ...baseItem(),
                type: 'comment',
                source: 'notebook',
                data: {
                    id: 'notebook-comment-1',
                    comment: 'Notebook note',
                    notebookShortId: 'note-1',
                    notebookTitle: 'Research',
                    timeInRecording: 5000,
                },
            } satisfies InspectorListItemNotebookComment,
            { source: 'notebook', comment: 'Notebook note', notebook_title: 'Research' },
        ],
        [
            'doctor',
            {
                ...baseItem(),
                type: 'doctor',
                tag: 'session options',
                data: { sampleRate: 1 },
            } satisfies InspectorListItemDoctor,
            { tag: 'session options', data: { sampleRate: 1 } },
        ],
        [
            'inactivity',
            {
                ...baseItem(),
                type: 'inactivity',
                durationMs: 65000,
            } satisfies InspectorListItemInactivity,
            { duration_ms: 65000 },
        ],
        [
            'session change',
            {
                ...baseItem(),
                type: 'session-change',
                tag: '$session_ending',
                data: { nextSessionId: 'next-session' },
            } satisfies InspectorListSessionChange,
            { tag: '$session_ending', next_session_id: 'next-session' },
        ],
        [
            'logs',
            {
                ...baseItem(),
                type: 'logs',
                data: {
                    uuid: 'log-1',
                    trace_id: 'trace-1',
                    span_id: 'span-1',
                    body: 'backend failed',
                    attributes: { route: '/api' },
                    timestamp: timestamp.toISOString(),
                    observed_timestamp: timestamp.toISOString(),
                    severity_text: 'error',
                    severity_number: 17,
                    level: 'error',
                    resource_attributes: { service: 'web' },
                    instrumentation_scope: 'django',
                    event_name: 'log',
                },
            } satisfies InspectorListItemLog,
            { level: 'error', body: 'backend failed', instrumentation_scope: 'django' },
        ],
        [
            'app state',
            {
                ...baseItem(),
                type: 'app-state',
                action: 'cart updated',
                stateEvent: { payload: { quantity: 2 } },
            } satisfies InspectorListItemAppState,
            { action: 'cart updated', state_event: { payload: { quantity: 2 } } },
        ],
        [
            'offline status',
            {
                ...baseItem(),
                type: 'offline-status',
                offline: true,
            } satisfies InspectorListOfflineStatusChange,
            { offline: true },
        ],
        [
            'browser visibility',
            {
                ...baseItem(),
                type: 'browser-visibility',
                status: 'hidden',
            } satisfies InspectorListBrowserVisibility,
            { status: 'hidden' },
        ],
        [
            'summary',
            {
                ...baseItem(),
                type: 'inspector-summary',
                clickCount: 2,
                keypressCount: 3,
                errorCount: 1,
            } satisfies InspectorListItemSummary,
            { click_count: 2, keypress_count: 3, error_count: 1 },
        ],
    ])('exports visible fields for %s items', (_, item, expectedDetails) => {
        const exportedItem = buildInspectorExportItem(item)

        expect(exportedItem.timestamp).toBe('2024-01-01T00:00:05.000Z')
        expect(exportedItem.time_in_recording_ms).toBe(5000)
        expect(exportedItem.window_number).toBe(1)
        expect(exportedItem.details).toMatchObject(expectedDetails)
    })

    it('builds a document from visible items and display groups', () => {
        const firstItem: InspectorListItemConsole = {
            ...baseItem({ key: 'console-1', search: 'Repeated failure' }),
            type: 'console',
            data: {
                timestamp: timestamp.valueOf(),
                windowId: 1,
                level: 'error',
                content: 'Repeated failure',
                lines: ['Repeated failure'],
                count: 1,
            },
        }
        const secondItem: InspectorListItemConsole = {
            ...firstItem,
            key: 'console-2',
            timeInRecording: 6000,
            timestamp: timestamp.add(1, 'second'),
        }
        const hiddenUnfilteredItem: InspectorListItemDoctor = {
            ...baseItem({ key: 'doctor-1' }),
            type: 'doctor',
            tag: 'hidden doctor event',
        }

        const document = buildDocument([firstItem, secondItem], [{ indices: [0, 1] }])

        expect(document.rows).toHaveLength(1)
        expect(document.row_count).toBe(1)
        expect(document.item_count).toBe(2)
        expect(document.truncated_logs).toBe(true)
        expect(document.filter_context).toMatchObject({
            search_query: 'checkout',
            enabled_mini_filters: ['events-pageview'],
            show_only_matching: true,
            group_repeated_items: true,
            tracked_window: 1,
        })
        expect(document.rows[0].group_count).toBe(2)
        expect(document.rows[0].items?.map((item) => item.key)).toEqual(['console-1', 'console-2'])
        expect(document.rows.map((row) => row.key)).not.toContain(hiddenUnfilteredItem.key)
    })

    it('formats clipboard text with grouped child rows and truncation note', () => {
        const item: InspectorListItemConsole = {
            ...baseItem({ key: 'console-1' }),
            type: 'console',
            data: {
                timestamp: timestamp.valueOf(),
                windowId: 1,
                level: 'warn',
                content: 'Retrying request',
                lines: ['Retrying request'],
                count: 1,
            },
        }

        const document = buildDocument(
            [item, { ...item, key: 'console-2', timeInRecording: 7000 }],
            [{ indices: [0, 1] }]
        )
        const clipboardText = formatInspectorExportDocumentForClipboard(document)

        expect(clipboardText).toContain('Session replay inspector for recording recording-1')
        expect(clipboardText).toContain('1 rows, 2 items')
        expect(clipboardText).toContain('Note: Backend logs are truncated')
        expect(clipboardText).toContain('[00:05] console: Retrying request')
        expect(clipboardText).toContain('  - [00:07] Retrying request')
    })

    it('handles an empty visible list', () => {
        const document = buildDocument([])

        expect(document.rows).toEqual([])
        expect(document.row_count).toBe(0)
        expect(document.item_count).toBe(0)
    })

    it('keeps window metadata in clipboard output when the window number is 0', () => {
        const item: InspectorListItemConsole = {
            ...baseItem({ key: 'console-1', windowNumber: 0 }),
            type: 'console',
            data: {
                timestamp: timestamp.valueOf(),
                windowId: 0,
                level: 'warn',
                content: 'Heartbeat',
                lines: ['Heartbeat'],
                count: 1,
            },
        }

        const document = buildDocument([item])
        const clipboardText = formatInspectorExportDocumentForClipboard(document)

        expect(document.rows[0].window_number).toBe(0)
        expect(clipboardText).toContain('window 0')
    })
})
