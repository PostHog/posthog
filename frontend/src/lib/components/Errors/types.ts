import { EventType, PersonType } from '~/types'

export interface ErrorTrackingException {
    stacktrace?: ErrorTrackingRawStackTrace | ErrorTrackingResolvedStackTrace
    module?: string
    id: string
    type: string
    value: string // can be an empty string
    mechanism?: {
        synthetic?: boolean
        handled?: boolean
        type: 'generic'
    }
}

export type ErrorTrackingRuntime =
    | 'web'
    | 'python'
    | 'node'
    | 'go'
    | 'rust'
    | 'ruby'
    | 'php'
    | 'java'
    | 'react-native'
    | 'android'
    | 'ios'
    | 'elixir'
    | 'swift'
    | 'dart'
    | 'flutter'
    | 'dotnet'
    | 'unknown'

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
    release: ErrorTrackingRelease | null
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
    module: string | null
    code_variables?: Record<string, unknown>
}

export interface ErrorTrackingFingerprint {
    fingerprint: string
    issue_id: string
    created_at: string
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
    runtime?: ErrorTrackingRuntime
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
    handled?: boolean
    appNamespace?: string
    appVersion?: string
}

export interface ReleaseGitMetadata {
    commit_id?: string
    remote_url?: string
    repo_name?: string
    branch?: string
}

export interface ErrorTrackingRelease {
    id: string
    metadata?: {
        git?: ReleaseGitMetadata
    }
    project?: string // Only present in recent releases (10-11-2025)
    version: string
    timestamp: string
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
