// Canonical definitions live in schema-signals.ts (synced between TS and Python).
// Re-exported here so existing consumers keep working.
import {
    EnrichedReviewer,
    RelevantCommit,
    SignalSourceProduct,
    SignalSourceType,
} from '~/queries/schema/schema-signals'
import type { UserBasicType } from '~/types'

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
    /** skill_name slug of the authoring scout, when scout-authored (raw slug — prettify with `scoutDisplayName`). */
    scout_name?: string | null
    /** PR URL from the latest implementation task run, if available. */
    implementation_pr_url?: string | null
    /** Reason code from the latest dismissal artefact (when archived). See dismissalReasons. */
    dismissal_reason?: string | null
    /** Free-form note from the latest dismissal artefact (when archived). */
    dismissal_note?: string | null
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
    /** Log artefacts are editable in place; null for write-once rows. */
    updated_at?: string | null
    /** Set when a human produced the artefact (drives the "by {name}" attribution byline). */
    created_by?: UserBasicType | null
    /** Set when an agent task produced the artefact (attribution reads "by agent"). */
    task_id?: string | null
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
    /** True when the enable came through the data-warehouse setup wizard, for `Signal source connected`. */
    viaSetupWizard?: boolean
}

export enum SignalSourceConfigStatus {
    RUNNING = 'running',
    COMPLETED = 'completed',
    FAILED = 'failed',
}

// ── Inbox 2.0 IA: tabs + scope ──────────────────────────────────────────────

export type InboxTabKey = 'pulls' | 'reports' | 'not-actionable' | 'runs' | 'archived' | 'config'

export const INBOX_TAB_KEYS: InboxTabKey[] = ['pulls', 'reports', 'not-actionable', 'runs', 'archived', 'config']

export const INBOX_TAB_LABEL: Record<InboxTabKey, string> = {
    pulls: 'Pull requests',
    reports: 'Reports',
    'not-actionable': 'Not actionable',
    runs: 'Runs',
    archived: 'Archive',
    config: 'Configuration',
}

/** What each tab holds, surfaced as the scene description while that tab is active so new users can orient themselves. */
export const INBOX_TAB_DESCRIPTION: Record<InboxTabKey, string> = {
    pulls: 'Pull requests agents opened to resolve reports. Review and merge them on GitHub.',
    reports: 'Issues and opportunities agents found in your product data, researched and prioritized for your review.',
    'not-actionable':
        'Reports judged not actionable – too vague, missing supporting evidence, or describing expected behavior.',
    runs: 'Project-wide list of agent runs, for debugging.',
    archived: 'Reports you archived. You can restore them to the inbox at any time.',
    config: 'Set up signal sources, scouts, and how autonomously agents can act.',
}

/**
 * The Configuration tab holds the agent-setup widgets. It only appears when the scene is too
 * narrow for the right-hand setup rail (see `AgentSetupColumn`); on wide viewports the rail
 * replaces it. Kept a real routing key so deep links and narrow-mode navigation work.
 */
export const INBOX_CONFIG_TAB_KEY: InboxTabKey = 'config'

/** Tabs that show a report-count chip. */
export const INBOX_REPORT_TAB_KEYS: InboxTabKey[] = ['pulls', 'reports', 'not-actionable', 'runs', 'archived']

/**
 * Tabs only visible to staff users (internal). The Not-actionable reports view is an internal
 * triage surface; everything else (including Runs) is public to any team member.
 */
export const INBOX_STAFF_ONLY_TAB_KEYS: InboxTabKey[] = ['not-actionable']

/** The flat report-list tabs that share the keyed reportListLogic + InboxReportList primitive. */
export const INBOX_FLAT_LIST_TAB_KEYS = ['pulls', 'reports', 'not-actionable', 'archived'] as const
export type InboxFlatListTabKey = (typeof INBOX_FLAT_LIST_TAB_KEYS)[number]

export interface InboxTabCounts {
    pulls: number
    reports: number
    'not-actionable': number
    runs: number
    archived: number
}

export const EMPTY_TAB_COUNTS: InboxTabCounts = { pulls: 0, reports: 0, 'not-actionable': 0, runs: 0, archived: 0 }

/** `for-you` (suggested-reviewer reports), `entire-project` (all), or `teammate:<uuid>`. */
export type InboxScope = 'for-you' | 'entire-project' | `teammate:${string}`

export const INBOX_SCOPE_FOR_YOU: InboxScope = 'for-you'
export const INBOX_SCOPE_ENTIRE_PROJECT: InboxScope = 'entire-project'

// ── SignalReport ↔ Task linkage ─────────────────────────────────────────────
// The task↔report association is the `task_run` artefact log (see artefactTypes.ts). The
// relationship vocabulary below is retained only for the task-creation kickoff path, where the
// backend still accepts `signal_report_task_relationship` (implementation) when starting a PR run.

export const SIGNAL_REPORT_TASK_RELATIONSHIPS = ['repo_selection', 'research', 'implementation'] as const

export type SignalReportTaskRelationship = (typeof SIGNAL_REPORT_TASK_RELATIONSHIPS)[number]

export const SIGNAL_REPORT_TASK_IMPLEMENTATION_RELATIONSHIP: SignalReportTaskRelationship = 'implementation'

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

// ── Runs (composed client-side from scout runs + signal-pipeline tasks) ───────

/** Whether a run-shaped task came from a headless scout or the signals pipeline. */
export type SignalRunKind = 'scout' | 'signal'

/**
 * One row in the Runs tab. Not a backend resource — `inboxSceneLogic` composes these from two
 * existing endpoints: scout runs (`signals/scout/runs`, kind `scout`) and signal-pipeline tasks
 * (`tasks?origin_product=signal_report`, kind `signal`), merged newest-first. Rows link out to the
 * standalone Tasks scene (`/tasks/{task_id}`).
 */
export interface SignalRun {
    task_id: string
    kind: SignalRunKind
    /** Scout: the `signals-scout-*` skill code name (shown verbatim). Signal: the report title. */
    title: string
    /** Latest run status, or null if unknown. Shares `TaskRunStatus` values. */
    status: SignalScoutRunStatus | null
    /** Signal runs: the inbox report this run belongs to, for linking to it. Null for scouts. */
    report_id: string | null
    created_at: string
}

// ── Scouts (backend SignalScoutConfigViewSet / SignalScoutRunViewSet) ─────────

/** Canonical (PostHog-shipped) vs custom (team-authored) scout, resolved server-side. */
export type ScoutOrigin = 'canonical' | 'custom'

/** Per-(team, skill) scout config. One row per `signals-scout-*` skill. */
export interface SignalScoutConfig {
    id: string
    /** The `signals-scout-*` skill this config controls. Fixed at creation. */
    skill_name: string
    /** What this scout investigates, sourced from the skill's `description` metadata. Empty if absent. */
    description: string
    /** Where this scout came from, resolved by the backend. Only `custom` scouts are deletable. */
    scout_origin: ScoutOrigin
    /** Whether this scout runs on its schedule. */
    enabled: boolean
    /** Whether the scout writes findings to the inbox. false = dry-run. */
    emit: boolean
    /** Minutes between runs (30–43200). */
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
    /** Bridge-row creation timestamp — the field the runs endpoint filters/orders on (the pagination cursor). */
    created_at: string
    started_at: string
    completed_at: string | null
    task_id?: string | null
    task_run_id?: string | null
    /** Relative deep-link to cloud's Tasks UI, e.g. `/project/{id}/tasks/{task}?runId={run}`. */
    task_url?: string | null
    summary: string
    emitted_count: number
    emitted_finding_ids: string[]
    /** Reports this run authored directly via the `emit_report` channel. Distinct from `emitted_count`
     * (weak `emit_signal` findings): a report-authoring run writes a full report instead of a finding. */
    emitted_report_ids: string[]
    /** Reports this run mutated via the `edit_report` channel (retitled/resummarized and/or appended a
     * note), deduped. Can target any inbox report, so these are generally not reports the run authored. */
    edited_report_ids: string[]
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
    /** Slug tags the scout attached to this finding (lowercase kebab-case, e.g. `cost-spike`). */
    tags: string[]
    source_id: string
    emitted_at: string
}

/** Minimal projection of the inbox report a scout finding grouped into (for the linked chip). */
export interface LinkedSignalReport {
    id: string
    title: string | null
}

/** One finding a run emitted, paired with the inbox report (if any) its signal grouped into. */
export interface SignalScoutEmissionReportLink {
    finding_id: string
    /** Deterministic `run:<run_id>:finding:<finding_id>` join key — the stable key into the emission set. */
    source_id: string
    /** The inbox report this finding linked to, or null if none could be resolved (not yet grouped, deduped, deleted). */
    report: LinkedSignalReport | null
}

// ── Report state transitions (backend `state` action: dismiss / snooze) ──────

export interface SignalReportStateRequest {
    state: 'suppressed' | 'potential'
    dismissal_reason?: string
    dismissal_note?: string
    /** Only honored for state === 'potential' (snooze): re-promote after N more signals. */
    snooze_for?: number
}
