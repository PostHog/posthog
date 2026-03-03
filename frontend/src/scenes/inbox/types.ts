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
    PENDING_INPUT = 'pending_input',
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

export interface SignalSourceConfig {
    id: string
    source_product: SignalSourceProduct
    source_type: SignalSourceType
    enabled: boolean
    config: Record<string, any>
    created_at: string
    updated_at: string
}

export enum SignalSourceProduct {
    SESSION_REPLAY = 'session_replay',
    LLM_ANALYTICS = 'llm_analytics',
}

export enum SignalSourceType {
    SESSION_ANALYSIS_CLUSTER = 'session_analysis_cluster',
    EVALUATION = 'evaluation',
}

export interface ToggleSignalSourceParams {
    sourceProduct: SignalSourceProduct
    sourceType: SignalSourceType
    enabled: boolean
    config?: Record<string, any>
}
