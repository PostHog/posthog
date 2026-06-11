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

/** P0 (highest) – P4 (lowest). Mirrors desktop `SignalReportPriority`. */
export type SignalReportPriority = 'P0' | 'P1' | 'P2' | 'P3' | 'P4'

/** Actionability judgment outcome. Mirrors desktop `SignalReportActionability`. */
export type SignalReportActionability = 'immediately_actionable' | 'requires_human_input' | 'not_actionable'

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
    /** Count of signals at the time the latest research run kicked off. */
    signals_at_run?: number
    /** P0–P4 from the priority judgment when the report is researched. */
    priority?: SignalReportPriority | null
    /** Actionability choice from the actionability judgment artefact. */
    actionability?: SignalReportActionability | null
    /** Whether the issue appears already fixed, from the actionability judgment artefact. */
    already_addressed?: boolean | null
    /** Distinct source products contributing signals to this report. */
    source_products?: string[]
    /** PR URL from the latest implementation task run, if available. */
    implementation_pr_url?: string | null
}

export enum SignalReportStatus {
    POTENTIAL = 'potential',
    CANDIDATE = 'candidate',
    IN_PROGRESS = 'in_progress',
    PENDING_INPUT = 'pending_input',
    READY = 'ready',
    RESOLVED = 'resolved',
    FAILED = 'failed',
    // Out-of-inbox terminal states (backend: SignalReport.Status). Excluded from every tab.
    DELETED = 'deleted',
    SUPPRESSED = 'suppressed',
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

// ── Inbox 2.0 IA: tabs + scope ──────────────────────────────────────────────

export type InboxTabKey = 'pulls' | 'reports' | 'runs'

export const INBOX_TAB_KEYS: InboxTabKey[] = ['pulls', 'reports', 'runs']

export const INBOX_TAB_LABEL: Record<InboxTabKey, string> = {
    pulls: 'Pull requests',
    reports: 'Reports',
    runs: 'Runs',
}

export interface InboxTabCounts {
    pulls: number
    reports: number
    runs: number
}

export const EMPTY_TAB_COUNTS: InboxTabCounts = { pulls: 0, reports: 0, runs: 0 }

/** `for-you` (suggested-reviewer reports), `entire-project` (all), or `teammate:<uuid>`. */
export type InboxScope = 'for-you' | 'entire-project' | `teammate:${string}`

export const INBOX_SCOPE_FOR_YOU: InboxScope = 'for-you'
export const INBOX_SCOPE_ENTIRE_PROJECT: InboxScope = 'entire-project'

// ── SignalReport ↔ Task linkage ─────────────────────────────────────────────

export const SIGNAL_REPORT_TASK_RELATIONSHIPS = ['repo_selection', 'research', 'implementation'] as const

export type SignalReportTaskRelationship = (typeof SIGNAL_REPORT_TASK_RELATIONSHIPS)[number]

export const SIGNAL_REPORT_TASK_IMPLEMENTATION_RELATIONSHIP: SignalReportTaskRelationship = 'implementation'

export interface SignalReportTask {
    id: string
    relationship: SignalReportTaskRelationship
    task_id: string
    created_at: string
}

// ── Autonomy config (per-user override; backend SignalUserAutonomyConfigView) ─

export interface SignalUserAutonomyConfig {
    id?: string
    autostart_priority: SignalReportPriority | null
    slack_notification_integration_id?: number | null
    slack_notification_channel?: string | null
    slack_notification_min_priority?: SignalReportPriority | null
    created_at?: string
    updated_at?: string
}

// ── Report state transitions (backend `state` action: dismiss / snooze) ──────

export interface SignalReportStateRequest {
    state: 'suppressed' | 'potential'
    dismissal_reason?: string
    dismissal_note?: string
    /** Only honored for state === 'potential' (snooze): re-promote after N more signals. */
    snooze_for?: number
}
