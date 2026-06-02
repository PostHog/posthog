import { dayjs } from 'lib/dayjs'
import { percentage } from 'lib/utils'
import { InsightWithQuery } from 'scenes/max/maxTypes'
import { urls } from 'scenes/urls'

import { InsightShortId } from '~/types'

import { PulseFindingType, PulseReference, PulseSensitivity, PulseTimelineMarker } from './pulseTypes'

export function formatSignedPct(pct: number): string {
    return `${pct >= 0 ? '+' : ''}${percentage(pct, 0)}`
}

export type ChangeDirection = 'up' | 'down' | 'flat'

export interface ChangeDescriptor {
    direction: ChangeDirection
    tone: 'success' | 'danger' | 'muted'
    label: string
}

// Tone is DIRECTIONAL, not sentiment: up=success/down=danger matches PostHog's web-analytics default. Pulse
// doesn't model per-metric polarity, so a rising error_rate reads "success" and a falling one "danger" — read
// the colour as "rose/fell", not "good/bad". Per-metric polarity (cf. web-analytics' reverseColors) is a
// tracked follow-up; the signed % label + arrow always state the literal direction regardless of colour.
export function describeChange(pct: number): ChangeDescriptor {
    if (pct === 0) {
        return { direction: 'flat', tone: 'muted', label: 'flat' }
    }
    if (pct > 0) {
        return { direction: 'up', tone: 'success', label: formatSignedPct(pct) }
    }
    return { direction: 'down', tone: 'danger', label: formatSignedPct(pct) }
}

// Seed question handed to the AI ("Explore with AI") — investigative, never asserts a cause.
export function buildMaxSeedPrompt(finding: PulseFindingType): string {
    const breakdown = finding.attribution_breakdown
    const breakdownClause =
        breakdown && breakdown.value
            ? ` The shift looks concentrated in ${breakdown.value}${breakdown.property ? ` (${breakdown.property})` : ''}.`
            : ''
    return (
        `Why did "${finding.metric_label}" change by ${formatSignedPct(finding.change_pct)} this week?` +
        breakdownClause +
        ` PostHog Pulse flagged it with this note: "${finding.narrative}". Help me dig into the likely causes.`
    )
}

const REFERENCE_TYPE_PREFIXES: Record<string, string> = {
    feature_flag: 'Flag',
    experiment: 'Experiment',
    annotation: 'Note',
}

// Turns a coincident-change reference into a labelled chip with an optional deep link, so the user can
// jump straight to the flag / experiment / annotation the narrative tied to this finding (the same idea
// as the replay links). A reference with no id renders as a label-only chip.
export function describeReference(ref: PulseReference): { label: string; to?: string } {
    const prefix = REFERENCE_TYPE_PREFIXES[ref.type]
    const label = prefix ? `${prefix}: ${ref.label}` : ref.label
    if (ref.id && ref.type === 'feature_flag') {
        return { label, to: urls.featureFlag(ref.id) }
    }
    if (ref.id && ref.type === 'experiment') {
        return { label, to: urls.experiment(ref.id) }
    }
    if (ref.id && ref.type === 'annotation') {
        return { label, to: urls.annotation(Number(ref.id)) }
    }
    return { label }
}

// Pull the saved-insight short id out of a finding's "View insight" deep link (/insights/<short_id>),
// so we can hand the AI the actual insight as structured context. Event-sourced findings have no saved
// insight and return null (the handoff then degrades to prompt-only).
export function findingShortId(finding: PulseFindingType): InsightShortId | null {
    const url = finding.metric_descriptor?.url
    if (typeof url !== 'string') {
        return null
    }
    // Short ids are nanoid-style (alphanumeric + - _); the strict class also rejects anything odd in
    // a malformed url before we cast to the branded type.
    const match = url.match(/\/insights\/([A-Za-z0-9_-]+)/)
    return match ? (match[1] as InsightShortId) : null
}

// Structured AI context for a finding: the actual insight (query + name) so the AI can read_data on the
// real metric instead of re-deriving it from a prompt. Null when the finding isn't backed by a saved insight.
export function buildFindingInsightContext(finding: PulseFindingType): InsightWithQuery | null {
    const shortId = findingShortId(finding)
    const query = finding.metric_descriptor?.query
    if (!shortId || !query) {
        return null
    }
    return { short_id: shortId, name: finding.metric_label, query }
}

// A guided, finding-specific "next step" that hands the AI a concrete investigative task. Deterministic
// (no LLM), and only for high-confidence shapes — a concentrated segment, or a coincident experiment/flag.
// Returns null when there's no specific lead (the generic "Explore with AI" covers that). Stays investigative:
// it proposes WHAT to look at next, never asserts a cause.
//
// Priority is segment first, then references: a concentrated segment is a direct statistical attribution
// for THIS metric, whereas a referenced experiment/flag is a coincidence the narrative tied to this finding
// — a strong but softer lead — so it's the fallback when no segment stands out. One step, not an accumulation.
export function suggestedNextStep(finding: PulseFindingType): { label: string; seed: string } | null {
    const metric = finding.metric_label
    const signed = formatSignedPct(finding.change_pct)
    const breakdown = finding.attribution_breakdown
    if (breakdown && breakdown.value) {
        const segment = String(breakdown.value)
        const prop = breakdown.property ? ` (${breakdown.property})` : ''
        return {
            label: `Dive into ${segment}`,
            seed:
                `"${metric}" changed by ${signed} this week, concentrated in ${segment}${prop}. ` +
                `Break this metric down within ${segment} and help me find what's driving the shift — ` +
                `a specific event, page, or cohort.`,
        }
    }
    const references = finding.evidence?.references ?? []
    const experiment = references.find((ref) => ref.type === 'experiment')
    if (experiment) {
        return {
            label: `Check the ${experiment.label} experiment`,
            seed:
                `"${metric}" changed by ${signed} this week while the "${experiment.label}" experiment was active. ` +
                `Help me check whether the experiment is driving this — compare exposed vs unexposed users.`,
        }
    }
    const flag = references.find((ref) => ref.type === 'feature_flag')
    if (flag) {
        return {
            label: `Check the ${flag.label} flag`,
            seed:
                `"${metric}" changed by ${signed} this week, coinciding with a change to the "${flag.label}" ` +
                `feature flag. Help me check whether the rollout is linked to this change.`,
        }
    }
    return null
}

// Build a finding's own timeline from the changes its narrative referenced (evidence.references), each
// carrying its own ISO timestamp — so it's self-contained and never depends on a digest-wide cap. Markers
// are positioned by time along axisStart..axisEnd (0..1, clamped) and sorted chronologically. Pure +
// deterministic. Returns [] when the finding cites nothing (with a timestamp) or the axis is missing.
export function buildFindingTimelineMarkers(
    finding: PulseFindingType,
    axisStart?: string,
    axisEnd?: string
): PulseTimelineMarker[] {
    const references = finding.evidence?.references ?? []
    if (!references.length || !axisStart || !axisEnd) {
        return []
    }
    const start = dayjs(axisStart)
    const span = dayjs(axisEnd).diff(start)
    if (span <= 0) {
        return []
    }
    const markers: PulseTimelineMarker[] = []
    references.forEach((ref, index) => {
        if (!ref.timestamp) {
            return // older findings may lack timestamps on their references — nothing to place
        }
        const fraction = dayjs(ref.timestamp).diff(start) / span
        const position = Number.isFinite(fraction) ? Math.min(1, Math.max(0, fraction)) : 0
        markers.push({
            key: `${ref.type}-${ref.id || index}-${ref.timestamp}`,
            type: ref.type,
            label: ref.label,
            change: ref.change,
            timestamp: ref.timestamp,
            position,
            to: describeReference(ref).to,
        })
    })
    return markers.sort((a, b) => a.position - b.position)
}

// Frontend mirror of the backend SENSITIVITY_PRESETS. Selecting a preset applies these thresholds locally.
export const SENSITIVITY_PRESETS: Record<
    Exclude<PulseSensitivity, 'custom'>,
    { min_change_pct: number; robust_z_threshold: number }
> = {
    conservative: { min_change_pct: 0.4, robust_z_threshold: 3.5 },
    balanced: { min_change_pct: 0.25, robust_z_threshold: 3.5 },
    sensitive: { min_change_pct: 0.15, robust_z_threshold: 3.0 },
}
