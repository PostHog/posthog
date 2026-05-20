// Canonical definitions live in schema-signals.ts (synced between TS and Python).
// Re-exported here so existing consumers keep working.
import {
    EnrichedReviewer,
    RelevantCommit,
    SignalSourceProduct,
    SignalSourceType,
} from '~/queries/schema/schema-signals'

export type { EnrichedReviewer, RelevantCommit }
export { SignalSourceProduct, SignalSourceType }

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
    is_suggested_reviewer: boolean
}

export enum SignalReportStatus {
    POTENTIAL = 'potential',
    CANDIDATE = 'candidate',
    IN_PROGRESS = 'in_progress',
    PENDING_INPUT = 'pending_input',
    READY = 'ready',
    RESOLVED = 'resolved',
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
    status: SignalSourceConfigStatus | null
}

export interface ToggleSignalSourceParams {
    sourceProduct: SignalSourceProduct
    sourceType: SignalSourceType
    enabled: boolean
    config?: Record<string, any>
}

export enum SignalSourceConfigStatus {
    RUNNING = 'running',
    COMPLETED = 'completed',
    FAILED = 'failed',
}
