// Pure (no-React) artefact helpers shared by the detail logic and the activity-log renderers.
// Mirrors the PostHog Code inbox's artefact-log domain helpers. Content shapes stay loose
// (`Record<string, any>` on the artefact) and are read through these typed accessors so legacy
// rows with extra/missing keys never crash a render.

import { identifierToHuman } from 'lib/utils/strings'

import { SignalReportArtefact } from '../../types'

/** Built-in signals pipeline product identifier on a `task_run` artefact. */
export const SIGNALS_PRODUCT = 'signals'

// ── Per-type content shapes (read defensively; treat every field as possibly absent) ─────────

export interface CodeReferenceContent {
    file_path: string
    start_line?: number
    end_line?: number
    contents?: string
    relevance_note?: string
}

export interface LineReferenceContent {
    file_path: string
    line?: number
    note?: string
    contents?: string
}

export interface CommitContent {
    repository: string
    branch: string
    commit_sha: string
    message: string
    note?: string
}

export interface TaskRunArtefactContent {
    task_id: string
    run_id?: string | null
    product: string
    type: string
}

export interface NoteContent {
    note: string
    author?: string
}

export interface QuestionContent {
    question: string
    answer?: string | null
    answered?: boolean
}

export interface AssociatedReportContent {
    report_id: string
    reason?: string
}

export interface SignalFindingContent {
    signal_id: string
    relevant_code_paths?: string[]
    verified?: boolean
}

export interface DismissalContent {
    reason?: string
    note?: string
}

export interface TitleChangeContent {
    old_title?: string | null
    new_title: string
}

export interface SummaryChangeContent {
    old_summary?: string | null
    new_summary: string
}

// ── Type labels ──────────────────────────────────────────────────────────────────────────────

/** Human label for each artefact type as it reads in the activity log header. */
export const ARTEFACT_TYPE_LABELS: Record<string, string> = {
    code_reference: 'Code referenced',
    line_reference: 'Line highlighted',
    commit: 'Commit pushed',
    task_run: 'Task run',
    note: 'Note added',
    question: 'Question asked',
    associated_report: 'Report linked',
    priority_judgment: 'Priority assessed',
    actionability_judgment: 'Actionability assessed',
    safety_judgment: 'Safety assessed',
    signal_finding: 'Signal investigated',
    suggested_reviewers: 'Reviewers suggested',
    repo_selection: 'Repo selected',
    dismissal: 'Report dismissed',
    video_segment: 'Video segment',
    title_change: 'Title edited',
    summary_change: 'Summary edited',
}

export function artefactTypeLabel(type: string): string {
    return ARTEFACT_TYPE_LABELS[type] ?? type
}

/**
 * The mono `file:line` location string shown next to the type label, or null when the artefact
 * type carries no location.
 */
export function artefactLocationLabel(artefact: SignalReportArtefact): string | null {
    if (artefact.type === 'code_reference') {
        const c = artefact.content as CodeReferenceContent
        if (!c?.file_path) {
            return null
        }
        if (c.start_line && c.end_line && c.start_line !== c.end_line) {
            return `${c.file_path}:${c.start_line}-${c.end_line}`
        }
        return c.start_line ? `${c.file_path}:${c.start_line}` : c.file_path
    }
    if (artefact.type === 'line_reference') {
        const c = artefact.content as LineReferenceContent
        if (!c?.file_path) {
            return null
        }
        return c.line ? `${c.file_path}:${c.line}` : c.file_path
    }
    return null
}

/**
 * Attribution byline source: "{first name or email}" for a human write, "agent" for a
 * task-attributed write, or null for a system/pipeline write (no byline). Only one of
 * `created_by` / `task_id` is set per row.
 */
export function artefactAttributionLabel(artefact: SignalReportArtefact): string | null {
    if (artefact.created_by) {
        return artefact.created_by.first_name?.trim() || artefact.created_by.email
    }
    if (artefact.task_id) {
        return 'agent'
    }
    return null
}

// ── Task-run purpose derivation (replaces the legacy SignalReportTask `relationship`) ──────────

/** A task↔report association's derived purpose. `other` covers custom-agent runs. */
export type ReportTaskPurpose = 'research' | 'implementation' | 'other'

/** Sort order for linked-task rows: implementation first, then research, then everything else. */
export const PURPOSE_ORDER: ReportTaskPurpose[] = ['implementation', 'research', 'other']

export interface DerivedPurpose {
    purpose: ReportTaskPurpose
    purposeLabel: string
}

/**
 * Derive a task's purpose + display label from its `task_run` artefact's `(product, type)` pair.
 * Returns null for `repo_selection` (pipeline plumbing, never displayed). The built-in signals
 * pipeline maps research/implementation to typed purposes; any other pair is `other`, labelled
 * from the humanized product + type. Mirrors the desktop `derivePurpose`.
 */
export function deriveTaskPurpose(content: TaskRunArtefactContent): DerivedPurpose | null {
    if (content.product === SIGNALS_PRODUCT) {
        if (content.type === 'research') {
            return { purpose: 'research', purposeLabel: 'Research' }
        }
        if (content.type === 'implementation') {
            return { purpose: 'implementation', purposeLabel: 'Implementation' }
        }
        if (content.type === 'repo_selection') {
            return null
        }
        return { purpose: 'other', purposeLabel: `Signals — ${identifierToHuman(content.type)}` }
    }
    return {
        purpose: 'other',
        purposeLabel: `${identifierToHuman(content.product)} — ${identifierToHuman(content.type)}`,
    }
}

/**
 * Short type label for a `task_run` artefact's badge in the activity log. Unlike `deriveTaskPurpose`
 * this never returns null — `repo_selection` is shown here ("Repo selection") because the activity
 * log is the full work-log, whereas the Runs list hides selection plumbing.
 */
export function taskRunTypeLabel(content: TaskRunArtefactContent): string {
    if (content.product === SIGNALS_PRODUCT) {
        const labels: Record<string, string> = {
            research: 'Research',
            implementation: 'Implementation',
            repo_selection: 'Repo selection',
        }
        return labels[content.type] ?? identifierToHuman(content.type)
    }
    return identifierToHuman(content.type)
}

/** Whether a `task_run` artefact came from a custom agent (non-signals product). */
export function isCustomAgentTaskRun(content: TaskRunArtefactContent): boolean {
    return content.product !== SIGNALS_PRODUCT
}
