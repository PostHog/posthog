import { combineUrl } from 'kea-router'
import { useState } from 'react'

import { IconExternal, IconList } from '@posthog/icons'
import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress/LemonProgress'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { urls } from 'scenes/urls'

import type {
    SignalsScoutEvidenceEntryApi,
    SignalsScoutSignalExtraApi,
} from 'products/signals/frontend/generated/api.schemas'

import { INBOX_SOURCE_OPTIONS } from '../../filterOptions'
import { SignalReportPriorityBadge } from '../badges/SignalReportPriorityBadge'
import { SignalCardShell } from './SignalCardShell'
import type { SignalCardEntry, SignalCardProps } from './types'

/** How many evidence rows to show before collapsing the rest behind a toggle. */
const EVIDENCE_PREVIEW_COUNT = 3

/** O(1) source-product → {label, icon} lookup, built once from the shared filter options. */
const SOURCE_BY_VALUE: Record<string, { label: string; icon: JSX.Element }> = Object.fromEntries(
    INBOX_SOURCE_OPTIONS.map((o) => [o.value, { label: o.label, icon: o.icon }])
)

/** Narrows a raw `extra` payload to the live Signals scout shape. */
export function isSignalsScoutExtra(value: unknown): value is Record<string, unknown> & SignalsScoutSignalExtraApi {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const extra = value as Record<string, unknown>
    return Array.isArray(extra.evidence) && typeof extra.skill_name === 'string' && typeof extra.confidence === 'number'
}

/**
 * Builds a deep link into the product an evidence entry came from, or null when no link applies.
 * Entity-keyed products need an `entityId`; `logs` is entity-less; unknown products get no link.
 */
export function scoutEvidenceUrl(sourceProduct: string, entityId?: string): string | null {
    switch (sourceProduct) {
        case 'error_tracking':
            return entityId ? urls.errorTrackingIssue(entityId) : null
        case 'session_replay':
            return entityId ? urls.replaySingle(entityId) : null
        case 'llm_analytics':
            return entityId ? urls.aiObservabilityTrace(entityId) : null
        case 'logs':
            return urls.logs()
        default:
            return null
    }
}

/** A single evidence row: source icon + eyebrow, the summary, and an optional deep link. */
function EvidenceRow({ entry }: { entry: SignalsScoutEvidenceEntryApi }): JSX.Element {
    const meta = SOURCE_BY_VALUE[entry.source_product]
    const url = scoutEvidenceUrl(entry.source_product, entry.entity_id ?? undefined)
    return (
        <li className="flex items-start gap-2 py-0.5">
            <span className="inline-flex shrink-0 items-center text-tertiary mt-0.5" aria-hidden>
                {meta ? meta.icon : <IconList />}
            </span>
            <div className="flex-1 min-w-0">
                <div className="text-xs font-medium text-tertiary">{meta?.label ?? entry.source_product}</div>
                <div className="text-sm text-primary">{entry.summary}</div>
            </div>
            {url && (
                <Link to={url} className="flex items-center gap-1 text-xs font-medium shrink-0">
                    View <IconExternal className="size-3" />
                </Link>
            )}
        </li>
    )
}

/** Truncated mono identifier for footer run/finding ids. Becomes a deep link when `to` is set. */
function MonoId({ label, value, to }: { label: string; value: string; to?: string }): JSX.Element {
    const display = value.length > 12 ? `${value.slice(0, 12)}…` : value
    if (to) {
        return (
            <Link to={to} className="inline-flex items-center gap-1 font-medium">
                <span>{label}</span>
                <span className="font-mono">{display}</span>
                <IconExternal className="size-3" />
            </Link>
        )
    }
    return (
        <span className="inline-flex items-center gap-1">
            <span>{label}</span>
            <span className="font-mono">{display}</span>
        </span>
    )
}

/** Richest inbox card: a cross-source scout finding with confidence, hypothesis, evidence, and run metadata. */
export function SignalsScoutSignalCard({ signal }: SignalCardProps): JSX.Element {
    const [showAllEvidence, setShowAllEvidence] = useState(false)

    const extra = signal.extra as Record<string, unknown> & SignalsScoutSignalExtraApi

    const confidencePercent = Math.round(extra.confidence * 100)
    const hypothesis = extra.hypothesis?.trim() || signal.content

    const evidence = extra.evidence ?? []
    const visibleEvidence = showAllEvidence ? evidence : evidence.slice(0, EVIDENCE_PREVIEW_COUNT)

    const tags = extra.tags ?? []
    const timeRange = extra.time_range

    // Deep link the run id straight to its Tasks run tab — only resolvable when the task id was
    // captured at emit time (absent on older emissions).
    const taskRunUrl = extra.task_id
        ? combineUrl(urls.taskDetail(extra.task_id), { runId: extra.task_run_id }).url
        : undefined

    return (
        <SignalCardShell
            signal={signal}
            // The scout's name now lives in the shared source line ("Scout · <name>"); keep just a
            // linked version here so the header doesn't repeat the name.
            label={
                <Link to={urls.inboxScout(extra.skill_name)} className="text-tertiary font-normal">
                    v{extra.skill_version}
                </Link>
            }
            rightSlot={<SignalReportPriorityBadge priority={extra.severity} />}
        >
            {/* Confidence meter. */}
            <div className="mb-2">
                <div className="flex items-center justify-between text-xs text-tertiary mb-0.5">
                    <span>Confidence</span>
                    <span className="tabular-nums">{confidencePercent}%</span>
                </div>
                <LemonProgress percent={confidencePercent} />
            </div>

            {/* Hypothesis — the prominent narrative of the finding. */}
            {hypothesis && (
                <LemonMarkdown className="text-sm text-primary mb-2" disableImages>
                    {hypothesis}
                </LemonMarkdown>
            )}

            {/* Tags as raw kebab slugs. */}
            {tags.length > 0 && (
                <div className="flex flex-wrap gap-1 mb-2">
                    {tags.map((tag) => (
                        <LemonTag key={tag} size="small" type="muted">
                            {tag}
                        </LemonTag>
                    ))}
                </div>
            )}

            {/* Time window the finding refers to. */}
            {timeRange && (
                <div className="text-xs text-tertiary mb-2">
                    {humanFriendlyDetailedTime(timeRange.date_from)} – {humanFriendlyDetailedTime(timeRange.date_to)}
                </div>
            )}

            {/* Evidence — the centerpiece, one row per source observation. */}
            {evidence.length > 0 && (
                <div className="border-t pt-2">
                    <div className="text-xs font-medium text-tertiary mb-1">Evidence</div>
                    <ul className="flex flex-col">
                        {visibleEvidence.map((entry, index) => (
                            <EvidenceRow key={`${entry.source_product}-${entry.entity_id ?? index}`} entry={entry} />
                        ))}
                    </ul>
                    {evidence.length > EVIDENCE_PREVIEW_COUNT && (
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            onClick={() => setShowAllEvidence(!showAllEvidence)}
                            className="mt-1"
                        >
                            {showAllEvidence ? 'Show fewer' : `Show all ${evidence.length}`}
                        </LemonButton>
                    )}
                </div>
            )}

            {/* Footer — run/finding identifiers and an optional trace link-out. */}
            <div className="flex items-center flex-wrap gap-x-3 gap-y-1 border-t pt-2 mt-2 text-xs text-tertiary">
                <MonoId label="Finding" value={extra.finding_id} />
                <MonoId label="Scout run" value={extra.scout_run_id} />
                {extra.task_id && <MonoId label="Task" value={extra.task_id} to={taskRunUrl} />}
                <MonoId label="Task run" value={extra.task_run_id} to={taskRunUrl} />
                {extra.mcp_trace_id && (
                    <>
                        <span className="flex-1" />
                        <Link
                            to={urls.aiObservabilityTrace(extra.mcp_trace_id)}
                            className="flex items-center gap-1 font-medium shrink-0"
                        >
                            View LLM trace <IconExternal className="size-3" />
                        </Link>
                    </>
                )}
            </div>
        </SignalCardShell>
    )
}

export const signalsScoutSignalCardEntry: SignalCardEntry = {
    key: 'signals_scout',
    matches: (signal) => signal.source_product === 'signals_scout' && isSignalsScoutExtra(signal.extra),
    Component: SignalsScoutSignalCard,
}
