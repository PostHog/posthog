import { dayjs } from 'lib/dayjs'
import { InspectorListItemPerformance } from 'scenes/session-recordings/apm/performanceEventDataLogic'
import {
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
} from 'scenes/session-recordings/player/inspector/playerInspectorLogic'

import { LogSeverityLevel } from '~/queries/schema/schema-general'
import { PerformanceEvent } from '~/types'

import { serializeInspectorItem, serializeInspectorItems } from './inspectorItemSerializers'

const FIXED_TS = dayjs('2026-01-15T12:34:56.000Z')

const base = {
    timestamp: FIXED_TS,
    timeInRecording: 12500,
    search: '',
    windowNumber: 1 as const,
    key: 'k',
}

const items: Record<string, InspectorListItem> = {
    event: {
        ...base,
        type: 'events',
        data: {
            id: 'e1',
            event: '$pageview',
            properties: { $pathname: '/checkout' },
            timestamp: FIXED_TS.toISOString(),
            elements: [],
            fullyLoaded: true,
            playerTime: 12500,
        },
    } as unknown as InspectorListItemEvent,
    consoleError: {
        ...base,
        type: 'console',
        data: {
            timestamp: FIXED_TS.valueOf(),
            windowId: 1,
            level: 'error',
            content: 'TypeError: cannot read x of undefined',
            count: 1,
            lines: ['TypeError: cannot read x of undefined', '    at handler (a.js:1:1)'],
            trace: ['    at handler (a.js:1:1)'],
        },
    } as InspectorListItemConsole,
    network: {
        ...base,
        type: 'network',
        data: {
            name: 'https://example.com/api/items',
            method: 'GET',
            response_status: 200,
            duration: 142,
            initiator_type: 'fetch',
        } as PerformanceEvent,
    } as InspectorListItemPerformance,
    log: {
        ...base,
        type: 'logs',
        data: {
            uuid: 'u',
            trace_id: 't',
            span_id: 's',
            body: 'request handled',
            attributes: { route: '/api/items', latency_ms: 142 },
            timestamp: FIXED_TS.toISOString(),
            observed_timestamp: FIXED_TS.toISOString(),
            severity_text: 'info' as LogSeverityLevel,
            severity_number: 9,
            level: 'info' as LogSeverityLevel,
            resource_attributes: {},
            instrumentation_scope: 'app',
            event_name: '',
        },
    } as InspectorListItemLog,
    doctor: {
        ...base,
        type: 'doctor',
        tag: 'snapshot-delay',
        data: { delay_ms: 1200 },
    } as InspectorListItemDoctor,
    appState: {
        ...base,
        type: 'app-state',
        action: 'cart/addItem',
        stateEvent: { itemId: 'sku-1', count: 1 },
    } as InspectorListItemAppState,
    offline: {
        ...base,
        type: 'offline-status',
        offline: true,
    } as InspectorListOfflineStatusChange,
    visibility: {
        ...base,
        type: 'browser-visibility',
        status: 'hidden',
    } as InspectorListBrowserVisibility,
    inactivity: {
        ...base,
        type: 'inactivity',
        durationMs: 5_000,
    } as InspectorListItemInactivity,
    sessionChange: {
        ...base,
        type: 'session-change',
        tag: '$session_starting',
        data: { nextSessionId: 'sess-2' },
    } as InspectorListSessionChange,
    summary: {
        ...base,
        type: 'inspector-summary',
        clickCount: 3,
        keypressCount: 5,
        errorCount: 1,
    } as InspectorListItemSummary,
    commentRegular: {
        ...base,
        type: 'comment',
        source: 'comment',
        data: { id: 'c1', content: 'note this', rich_content: null },
    } as unknown as InspectorListItemComment,
    commentNotebook: {
        ...base,
        type: 'comment',
        source: 'notebook',
        data: {
            id: 'n1',
            notebookShortId: 'nb1',
            notebookTitle: 'QA notes',
            comment: 'flaky here',
            timeInRecording: 12500,
        },
    } as InspectorListItemNotebookComment,
}

describe('serializeInspectorItem (text)', () => {
    it.each(Object.entries(items))('produces non-empty text for %s', (_key, item) => {
        const out = serializeInspectorItem(item, 'text')
        expect(out).toMatch(/^\[/) // begins with timestamp prefix
        expect(out.length).toBeGreaterThan(0)
    })

    it('formats network with method, url, status, duration', () => {
        const out = serializeInspectorItem(items.network, 'text')
        expect(out).toContain('GET')
        expect(out).toContain('https://example.com/api/items')
        expect(out).toContain('-> 200')
        expect(out).toContain('(142ms)')
    })

    it('formats console error with level and trace lines', () => {
        const out = serializeInspectorItem(items.consoleError, 'text')
        expect(out).toContain('ERROR')
        expect(out).toContain('TypeError: cannot read x of undefined')
        expect(out).toContain('at handler (a.js:1:1)')
    })

    it('formats logs with attribute lines', () => {
        const out = serializeInspectorItem(items.log, 'text')
        expect(out).toContain('INFO')
        expect(out).toContain('request handled')
        expect(out).toContain('route=/api/items')
        expect(out).toContain('latency_ms=142')
    })

    it('uses event description when available', () => {
        const out = serializeInspectorItem(items.event, 'text')
        expect(out).toContain('event $pageview')
        expect(out).toContain('/checkout')
    })

    it('renders comment body for regular comment', () => {
        const out = serializeInspectorItem(items.commentRegular, 'text')
        expect(out).toContain('comment note this')
    })

    it('renders notebook title for notebook comment', () => {
        const out = serializeInspectorItem(items.commentNotebook, 'text')
        expect(out).toContain('QA notes')
        expect(out).toContain('flaky here')
    })
})

describe('serializeInspectorItem (json)', () => {
    it.each(Object.entries(items))('produces valid JSON for %s', (_key, item) => {
        const out = serializeInspectorItem(item, 'json')
        const parsed = JSON.parse(out)
        expect(parsed.type).toBe(item.type)
        expect(parsed.timestamp).toBe(FIXED_TS.toISOString())
        expect(parsed.timeInRecording).toBe(12500)
    })

    it('includes typed data field for event items', () => {
        const out = JSON.parse(serializeInspectorItem(items.event, 'json'))
        expect(out.data.event).toBe('$pageview')
        expect(out.data.properties.$pathname).toBe('/checkout')
    })

    it('includes tag and data for doctor items', () => {
        const out = JSON.parse(serializeInspectorItem(items.doctor, 'json'))
        expect(out.tag).toBe('snapshot-delay')
        expect(out.data.delay_ms).toBe(1200)
    })

    it('includes action and stateEvent for app-state items', () => {
        const out = JSON.parse(serializeInspectorItem(items.appState, 'json'))
        expect(out.action).toBe('cart/addItem')
        expect(out.stateEvent.itemId).toBe('sku-1')
    })
})

describe('serializeInspectorItems (bulk)', () => {
    const allItems = Object.values(items)

    it('excludes synthetic types (summary, inactivity, session-change) from bulk output', () => {
        const result = serializeInspectorItems(allItems, 'json')
        const parsed = JSON.parse(result.output)
        const types = new Set(parsed.items.map((i: { type: string }) => i.type))
        expect(types.has('inspector-summary')).toBe(false)
        expect(types.has('inactivity')).toBe(false)
        expect(types.has('session-change')).toBe(false)
        expect(parsed.item_count).toBe(result.itemCount)
    })

    it('includes header metadata in text output', () => {
        const result = serializeInspectorItems(allItems, 'text', {
            sessionId: 'sess-abc',
            recordingStart: FIXED_TS.toISOString(),
            filterSummary: 'console errors only',
        })
        expect(result.output).toContain('# Session: sess-abc')
        expect(result.output).toContain('# Filter: console errors only')
        expect(result.output).toContain('# Items:')
    })

    it('includes session and filter metadata in json payload', () => {
        const result = serializeInspectorItems(allItems, 'json', {
            sessionId: 'sess-abc',
            filterSummary: 'errors only',
        })
        const parsed = JSON.parse(result.output)
        expect(parsed.session_id).toBe('sess-abc')
        expect(parsed.filter_summary).toBe('errors only')
        expect(Array.isArray(parsed.items)).toBe(true)
    })

    it('returns truncated=false when under the cap', () => {
        const result = serializeInspectorItems(allItems, 'json')
        expect(result.truncated).toBe(false)
    })

    it('truncates when over the cap', () => {
        const oneItem = items.event
        const many = Array.from({ length: 10_010 }, () => oneItem)
        const result = serializeInspectorItems(many, 'json')
        expect(result.truncated).toBe(true)
        expect(result.itemCount).toBe(10_000)
        const parsed = JSON.parse(result.output)
        expect(parsed.items).toHaveLength(10_000)
        expect(parsed.truncated).toBe(true)
    })

    it('handles empty input gracefully in both formats', () => {
        expect(serializeInspectorItems([], 'json').itemCount).toBe(0)
        const text = serializeInspectorItems([], 'text')
        expect(text.itemCount).toBe(0)
        expect(text.output).toContain('# Items: 0')
    })
})
