import { EventType, PersonType } from '~/types'

export interface ErrorTrackingException {
    stacktrace?: ErrorTrackingRawStackTrace | ErrorTrackingResolvedStackTrace
    module: string
    id: string
    type: string
    value: string
    mechanism?: {
        synthetic?: boolean
        handled?: boolean
        type: 'generic'
    }
}

export type ErrorTrackingRuntime = 'web' | 'python' | 'node' | 'unknown'

interface ErrorTrackingRawStackTrace {
    type: 'raw'
    frames: any[] // TODO: type more concretely if we end up needing this (right now we show the $cymbal_errors instead)
}
interface ErrorTrackingResolvedStackTrace {
    type: 'resolved'
    frames: ErrorTrackingStackFrame[]
}

export interface ErrorTrackingStackFrameRecord {
    id: string
    raw_id: string
    created_at: string
    resolved: boolean
    context: ErrorTrackingStackFrameContext | null
    contents: ErrorTrackingStackFrame // For now, while we're not 100% on content structure
    symbol_set_ref: ErrorTrackingSymbolSet['ref']
}

export type ErrorTrackingStackFrameContext = {
    before: ErrorTrackingStackFrameContextLine[]
    line: ErrorTrackingStackFrameContextLine
    after: ErrorTrackingStackFrameContextLine[]
}
export type ErrorTrackingStackFrameContextLine = { number: number; line: string }

export interface ErrorTrackingStackFrame {
    raw_id: string
    mangled_name: string
    line: number | null
    column: number | null
    source: string | null
    in_app: boolean
    resolved_name: string | null
    lang: string
    resolved: boolean
    resolve_failure: string | null
}

export interface ErrorTrackingSymbolSet {
    id: string
    ref: string
    team_id: number
    created_at: string
    storage_ptr: string | null
    failure_reason: string | null
}

interface FingerprintFrame {
    type: 'frame'
    raw_id: string
    pieces: string[]
}

interface FingerprintException {
    type: 'exception'
    id: string // Exception ID
    pieces: string[]
}

interface FingerprintManual {
    type: 'manual'
}

export type FingerprintRecordPart = FingerprintManual | FingerprintFrame | FingerprintException

export interface ExceptionAttributes {
    ingestionErrors?: string[]
    runtime: ErrorTrackingRuntime
    type?: string
    value?: string
    synthetic?: boolean
    lib?: string
    libVersion?: string
    browser?: string
    browserVersion?: string
    os?: string
    osVersion?: string
    sentryUrl?: string
    level?: string
    url?: string
    handled: boolean
}

export type SymbolSetStatus = 'valid' | 'invalid'
export type SymbolSetStatusFilter = SymbolSetStatus | 'all'
export type ErrorEventProperties = EventType['properties']
export type ErrorEventId = NonNullable<EventType['uuid']>

export type ErrorEventType = {
    uuid: ErrorEventId
    timestamp: string
    properties: ErrorEventProperties
    person: PersonType
}
