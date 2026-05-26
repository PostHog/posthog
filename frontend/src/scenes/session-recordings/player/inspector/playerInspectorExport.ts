import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { dayjs } from 'lib/dayjs'
import { eventToDescription, humanFriendlyDuration } from 'lib/utils'

import { getCoreFilterDefinition } from '~/taxonomy/helpers'

import type { SharedListMiniFilter } from './miniFiltersLogic'
import type { DisplayGroup, InspectorListItem, InspectorListItemType } from './playerInspectorLogic'

export interface InspectorExportItem {
    key: string
    type: InspectorListItemType
    timestamp: string
    time_in_recording_ms: number
    label: string
    search: string
    window_id?: number
    window_number?: number | '?'
    highlight?: 'danger' | 'warning' | 'primary'
    details: Record<string, unknown>
}

export interface InspectorExportRow extends InspectorExportItem {
    group_count: number
    items?: InspectorExportItem[]
}

export interface InspectorExportFilterContext {
    search_query: string
    enabled_mini_filters: string[]
    show_only_matching: boolean
    group_repeated_items: boolean
    tracked_window: number | null
}

export interface InspectorExportDocument {
    recording_id: string
    exported_at: string
    filter_context: InspectorExportFilterContext
    truncated_logs: boolean
    row_count: number
    item_count: number
    rows: InspectorExportRow[]
}

interface BuildInspectorExportDocumentParams {
    sessionRecordingId: string
    exportedAt: string
    items: InspectorListItem[]
    displayGroups: DisplayGroup[]
    searchQuery: string
    miniFilters: SharedListMiniFilter[]
    showOnlyMatching: boolean
    groupRepeatedItems: boolean
    trackedWindow: number | null
    logsHasMore: boolean
}

interface BuildInspectorExportRowParams {
    items: InspectorListItem[]
    displayGroup: DisplayGroup
}

function definedRecord(record: Record<string, unknown>): Record<string, unknown> {
    return Object.fromEntries(Object.entries(record).filter(([, value]) => value !== undefined))
}

function formatTimestamp(item: InspectorListItem): string {
    return item.timestamp.toISOString()
}

function formatTimeInRecording(milliseconds: number): string {
    const totalSeconds = Math.max(Math.floor(milliseconds / 1000), 0)
    const minutes = Math.floor(totalSeconds / 60)
    const seconds = totalSeconds % 60
    return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

function eventLabel(item: Extract<InspectorListItem, { type: 'events' }>): string {
    const eventName = item.data.event ?? 'Event'
    const eventDisplayName = getCoreFilterDefinition(eventName, TaxonomicFilterGroupType.Events)?.label ?? eventName
    const description = eventToDescription(item.data)
    return [eventDisplayName, description].filter(Boolean).join(' ')
}

function itemLabel(item: InspectorListItem): string {
    switch (item.type) {
        case 'events':
            return eventLabel(item)
        case 'console':
            return item.data.content
        case 'network': {
            const prefix = item.data.entry_type === 'navigation' ? 'Navigated to' : item.data.method
            return [prefix, item.data.name].filter(Boolean).join(' ') || 'Network event'
        }
        case 'comment':
            return item.source === 'notebook' ? item.data.comment : item.data.content || 'Comment'
        case 'doctor':
            return item.tag
        case 'logs':
            return `${item.data.level}: ${item.data.body}`
        case 'app-state':
            return item.action
        case 'offline-status':
            return item.offline ? 'Browser went offline' : 'Browser returned online'
        case 'browser-visibility':
            return `Window became ${item.status}`
        case 'session-change':
            return item.tag === '$session_starting' ? 'Previous session available' : 'Next session available'
        case 'inactivity':
            return `${humanFriendlyDuration(item.durationMs / 1000)} of inactivity`
        case 'inspector-summary':
            return `${item.clickCount ?? 0} clicks, ${item.keypressCount ?? 0} keystrokes, ${
                item.errorCount ?? 0
            } errors`
    }
}

function itemDetails(item: InspectorListItem): Record<string, unknown> {
    switch (item.type) {
        case 'events':
            return definedRecord({
                event: item.data.event,
                event_id: item.data.id,
                distinct_id: item.data.distinct_id,
                properties: item.data.properties,
                fully_loaded: item.data.fullyLoaded,
            })
        case 'console':
            return definedRecord({
                level: item.data.level,
                content: item.data.content,
                lines: item.data.lines,
                trace: item.data.trace,
                repeat_count: item.data.count,
            })
        case 'network':
            return definedRecord({
                entry_type: item.data.entry_type,
                initiator_type: item.data.initiator_type,
                method: item.data.method,
                name: item.data.name,
                current_url: item.data.current_url,
                response_status: item.data.response_status,
                start_time: item.data.start_time ?? item.data.fetch_start,
                duration: item.data.duration,
                end_time: item.data.end_time,
                transfer_size: item.data.transfer_size,
                decoded_body_size: item.data.decoded_body_size,
                encoded_body_size: item.data.encoded_body_size,
                request_headers: item.data.request_headers,
                response_headers: item.data.response_headers,
                request_body: item.data.request_body,
                response_body: item.data.response_body,
            })
        case 'comment':
            return item.source === 'notebook'
                ? definedRecord({
                      source: item.source,
                      comment: item.data.comment,
                      notebook_short_id: item.data.notebookShortId,
                      notebook_title: item.data.notebookTitle,
                  })
                : definedRecord({
                      source: item.source,
                      content: item.data.content,
                      created_by: item.data.created_by
                          ? {
                                id: item.data.created_by.id,
                                email: item.data.created_by.email,
                                first_name: item.data.created_by.first_name,
                                last_name: item.data.created_by.last_name,
                            }
                          : undefined,
                  })
        case 'doctor':
            return definedRecord({ tag: item.tag, data: item.data })
        case 'logs':
            return definedRecord({
                level: item.data.level,
                severity_text: item.data.severity_text,
                severity_number: item.data.severity_number,
                body: item.data.body,
                attributes: item.data.attributes,
                resource_attributes: item.data.resource_attributes,
                instrumentation_scope: item.data.instrumentation_scope,
                trace_id: item.data.trace_id,
                span_id: item.data.span_id,
            })
        case 'app-state':
            return definedRecord({ action: item.action, state_event: item.stateEvent })
        case 'offline-status':
            return { offline: item.offline }
        case 'browser-visibility':
            return { status: item.status }
        case 'session-change':
            return definedRecord({
                tag: item.tag,
                previous_session_id: item.data.previousSessionId,
                next_session_id: item.data.nextSessionId,
                change_reason: item.data.changeReason,
            })
        case 'inactivity':
            return { duration_ms: item.durationMs }
        case 'inspector-summary':
            return {
                click_count: item.clickCount,
                keypress_count: item.keypressCount,
                error_count: item.errorCount,
            }
    }
}

export function buildInspectorExportItem(item: InspectorListItem): InspectorExportItem {
    const exportItem: InspectorExportItem = {
        key: item.key,
        type: item.type,
        timestamp: formatTimestamp(item),
        time_in_recording_ms: item.timeInRecording,
        label: itemLabel(item),
        search: item.search,
        details: itemDetails(item),
    }

    if (item.windowId !== undefined) {
        exportItem.window_id = item.windowId
    }
    if (item.windowNumber !== undefined) {
        exportItem.window_number = item.windowNumber
    }
    if (item.highlightColor !== undefined) {
        exportItem.highlight = item.highlightColor
    }

    return exportItem
}

export function buildInspectorExportRow({
    items,
    displayGroup,
}: BuildInspectorExportRowParams): InspectorExportRow | null {
    const groupedItems = displayGroup.indices.map((index) => items[index]).filter((item) => !!item)
    const firstItem = groupedItems[0]

    if (!firstItem) {
        return null
    }

    const row: InspectorExportRow = {
        ...buildInspectorExportItem(firstItem),
        group_count: groupedItems.length,
    }

    if (groupedItems.length > 1) {
        row.items = groupedItems.map(buildInspectorExportItem)
    }

    return row
}

export function buildInspectorExportDocument({
    sessionRecordingId,
    exportedAt,
    items,
    displayGroups,
    searchQuery,
    miniFilters,
    showOnlyMatching,
    groupRepeatedItems,
    trackedWindow,
    logsHasMore,
}: BuildInspectorExportDocumentParams): InspectorExportDocument {
    const rows = displayGroups.flatMap((displayGroup) => {
        const row = buildInspectorExportRow({ items, displayGroup })
        return row ? [row] : []
    })

    return {
        recording_id: sessionRecordingId,
        exported_at: exportedAt,
        filter_context: {
            search_query: searchQuery,
            enabled_mini_filters: miniFilters.filter((filter) => !!filter.enabled).map((filter) => filter.key),
            show_only_matching: showOnlyMatching,
            group_repeated_items: groupRepeatedItems,
            tracked_window: trackedWindow,
        },
        truncated_logs: logsHasMore,
        row_count: rows.length,
        item_count: rows.reduce((count, row) => count + row.group_count, 0),
        rows,
    }
}

function formatInspectorExportRowForClipboard(row: InspectorExportRow): string {
    const metadata = [
        row.window_number != null ? `window ${row.window_number}` : null,
        row.highlight ? row.highlight : null,
        row.group_count > 1 ? `${row.group_count} items` : null,
    ].filter(Boolean)

    const title = `[${formatTimeInRecording(row.time_in_recording_ms)}] ${row.type}: ${row.label}`
    const metadataText = metadata.length ? ` (${metadata.join(', ')})` : ''

    if (!row.items?.length) {
        return `${title}${metadataText}`
    }

    const childRows = row.items
        .map((item) => `  - [${formatTimeInRecording(item.time_in_recording_ms)}] ${item.label}`)
        .join('\n')

    return `${title}${metadataText}\n${childRows}`
}

export function stringifyInspectorExportDocument(document: InspectorExportDocument): string {
    const seen = new WeakSet<object>()
    const replacer = (_key: string, value: unknown): unknown => {
        if (typeof value === 'bigint') {
            return value.toString()
        }
        if (typeof value === 'object' && value !== null) {
            if (seen.has(value)) {
                return '[Circular]'
            }
            seen.add(value)
        }
        return value
    }
    return JSON.stringify(document, replacer, 2)
}

export function formatInspectorExportDocumentForClipboard(document: InspectorExportDocument): string {
    const exportedAt = dayjs(document.exported_at).format('YYYY-MM-DD HH:mm:ss')
    const truncatedLogsLine = document.truncated_logs
        ? '\nNote: Backend logs are truncated because more logs are available.'
        : ''

    return [
        `Session replay inspector for recording ${document.recording_id}`,
        `Exported at ${exportedAt}`,
        `${document.row_count} rows, ${document.item_count} items${truncatedLogsLine}`,
        '',
        document.rows.map(formatInspectorExportRowForClipboard).join('\n'),
    ].join('\n')
}
