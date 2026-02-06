export interface SignalReport {
    id: string
    title: string | null
    summary: string | null
    status: SignalReportStatus
    total_weight: number
    signal_count: number
    relevant_user_count: number | null
    created_at: string
    updated_at: string
    artefact_count: number
}

export enum SignalReportStatus {
    POTENTIAL = 'potential',
    CANDIDATE = 'candidate',
    IN_PROGRESS = 'in_progress',
    READY = 'ready',
    FAILED = 'failed',
}

export interface SignalReportArtefact {
    id: string
    type: string
    content: Record<string, any>
    created_at: string
}

export interface SignalReportArtefactResponse {
    results: SignalReportArtefact[]
    count: number
}

export interface SignalReportPipelineMetadata {
    algorithm: string
    cluster_size: number
    intra_cluster_distance_p95: number | null
    is_new_cluster: boolean
    matched_report_id: string | null
    match_distance: number | null
    labeling: {
        actionable: boolean
        model: string
        segment_sample_count: number
        relevant_user_count: number
        occurrence_count: number
    } | null
}

export interface SignalReportDebugSegment {
    document_id: string
    content: string
    session_id: string | null
    timestamp: string | null
    centroid_distance: number | null
}

export interface SignalReportDebugSessionExport {
    id: number
    export_format: string
    created_at: string | null
    content_location: string | null
    expires_after: string | null
}

export interface SignalReportDebugSession {
    session_id: string
    exports: SignalReportDebugSessionExport[]
}

export interface SignalReportDebugResponse {
    id: string
    title: string | null
    summary: string | null
    status: string
    total_weight: number
    signal_count: number
    relevant_user_count: number | null
    created_at: string
    updated_at: string
    pipeline_metadata: SignalReportPipelineMetadata | null
    segments: SignalReportDebugSegment[]
    sessions: SignalReportDebugSession[]
}
