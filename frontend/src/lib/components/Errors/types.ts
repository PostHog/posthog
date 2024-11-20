export interface ErrorTrackingStackFrameRecord {
    id: string
    raw_id: string
    created_at: string
    symbol_set: string
    resolved: boolean
    context: string | null // TODO - switch this to the structure we've discussed once the migration is merged
    contents: ErrorTrackingStackFrame // For now, while we're not 100% on content structure
}

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
