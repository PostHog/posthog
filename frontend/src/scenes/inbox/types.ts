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

/** Actionability values that represent a report worth acting on — drives the Reports tab filter and the Create PR gate. */
export const ACTIONABLE_ACTIONABILITY_VALUES: SignalReportActionability[] = [
    'immediately_actionable',
    'requires_human_input',
]

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

export type InboxTabKey = 'pulls' | 'reports' | 'not-actionable' | 'runs' | 'config'

export const INBOX_TAB_KEYS: InboxTabKey[] = ['pulls', 'reports', 'not-actionable', 'runs', 'config']

export const INBOX_TAB_LABEL: Record<InboxTabKey, string> = {
    pulls: 'Pull requests',
    reports: 'Reports',
    'not-actionable': 'Not actionable',
    runs: 'Runs',
    config: 'Configuration',
}

/**
 * The Configuration tab holds the agent-setup widgets. It only appears when the scene is too
 * narrow for the right-hand setup rail (see `AgentSetupColumn`); on wide viewports the rail
 * replaces it. Kept a real routing key so deep links and narrow-mode navigation work.
 */
export const INBOX_CONFIG_TAB_KEY: InboxTabKey = 'config'

/** Tabs that show a report-count chip. */
export const INBOX_REPORT_TAB_KEYS: InboxTabKey[] = ['pulls', 'reports', 'not-actionable', 'runs']

/**
 * Tabs only visible to staff users (internal). Non-staff see Pull requests + Reports.
 * Not-actionable reports and the project-wide Runs debug view are internal.
 */
export const INBOX_STAFF_ONLY_TAB_KEYS: InboxTabKey[] = ['not-actionable', 'runs']

/** The three flat report-list tabs that share the keyed reportListLogic + InboxReportList primitive. */
export const INBOX_FLAT_LIST_TAB_KEYS = ['pulls', 'reports', 'not-actionable'] as const
export type InboxFlatListTabKey = (typeof INBOX_FLAT_LIST_TAB_KEYS)[number]

export interface InboxTabCounts {
    pulls: number
    reports: number
    'not-actionable': number
    runs: number
}

export const EMPTY_TAB_COUNTS: InboxTabCounts = { pulls: 0, reports: 0, 'not-actionable': 0, runs: 0 }

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

// ── Team-level autonomy config (backend SignalTeamConfigViewSet; singleton per team) ─

export interface SignalTeamConfig {
    id?: string
    /** Team-wide default PR auto-start threshold. null = never auto-start by default. */
    default_autostart_priority: SignalReportPriority | null
    /** Default Slack channel for this team's inbox notifications. */
    default_slack_notification_channel?: string | null
    /** Per-repo base-branch overrides for auto-started PRs, keyed by 'org/repo'. */
    autostart_base_branches?: Record<string, string>
    created_at?: string
    updated_at?: string
}

// ── Scouts (backend SignalScoutConfigViewSet / SignalScoutRunViewSet) ─────────

/** Per-(team, skill) scout config. One row per `signals-scout-*` skill. */
export interface SignalScoutConfig {
    id: string
    /** The `signals-scout-*` skill this config controls. Fixed at creation. */
    skill_name: string
    /** Whether this scout runs on its schedule. */
    enabled: boolean
    /** Whether the scout writes findings to the inbox. false = dry-run. */
    emit: boolean
    /** Minutes between runs (10–43200). */
    run_interval_minutes: number
    /** When the coordinator last dispatched this scout; null if never. */
    last_run_at: string | null
    created_at: string
}

/** Editable subset of a scout config (PATCH `signals/scout/configs/{id}`). */
export interface SignalScoutConfigUpdate {
    enabled?: boolean
    emit?: boolean
    run_interval_minutes?: number
}

/** Status from the linked TaskRun behind a scout run. */
export type SignalScoutRunStatus = 'not_started' | 'queued' | 'in_progress' | 'completed' | 'failed' | 'cancelled'

/** Lightweight projection of a scout run row (newest-first list response). */
export interface SignalScoutRunSummary {
    run_id: string
    skill_name: string
    skill_version: number
    status: SignalScoutRunStatus
    started_at: string
    completed_at: string | null
    task_id?: string | null
    task_run_id?: string | null
    /** Relative deep-link to cloud's Tasks UI, e.g. `/project/{id}/tasks/{task}?runId={run}`. */
    task_url?: string | null
    summary: string
    emitted_count: number
    emitted_finding_ids: string[]
}

/** One finding a scout run emitted to the inbox. */
export interface SignalScoutEmission {
    id: string
    run_id: string
    finding_id: string
    description: string
    weight: number
    confidence: number
    severity: SignalReportPriority | null
    source_id: string
    emitted_at: string
}

// ── Report state transitions (backend `state` action: dismiss / snooze) ──────

export interface SignalReportStateRequest {
    state: 'suppressed' | 'potential'
    dismissal_reason?: string
    dismissal_note?: string
    /** Only honored for state === 'potential' (snooze): re-promote after N more signals. */
    snooze_for?: number
}
