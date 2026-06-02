import { humanFriendlyLargeNumber, percentage } from 'lib/utils'
import { InsightWithQuery } from 'scenes/max/maxTypes'
import { urls } from 'scenes/urls'

import { InsightShortId } from '~/types'

import { PulseFindingType, PulseReference, PulseSensitivity } from './pulseTypes'

export function formatSignedPct(pct: number): string {
    return `${pct >= 0 ? '+' : ''}${percentage(pct, 0)}`
}

export function formatSignedNumber(value: number): string {
    // humanFriendlyLargeNumber abbreviates large values (43,106,067,556 -> "43.1B") and already
    // prefixes negatives with "-"; we add "+" only for positives (a flat 0 stays unsigned).
    return `${value > 0 ? '+' : ''}${humanFriendlyLargeNumber(value)}`
}

// Compact absolute-change line shown on a finding card, e.g. "179 this week vs 85/wk typical (+94)"
// or "43.1B this week vs 21.3B/wk typical (+21.8B)". Carries the real numbers so the narrative can
// focus on where the change concentrated and why.
export function describeAbsoluteChange(finding: PulseFindingType): string {
    const current = humanFriendlyLargeNumber(finding.current_value)
    const baseline = humanFriendlyLargeNumber(finding.baseline_value)
    const delta = formatSignedNumber(finding.current_value - finding.baseline_value)
    return `${current} this week vs ${baseline}/wk typical (${delta})`
}

export type ChangeDirection = 'up' | 'down' | 'flat'

export interface ChangeDescriptor {
    direction: ChangeDirection
    tone: 'success' | 'danger' | 'muted'
    label: string
}

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

export const ROBUST_Z_TOOLTIP =
    'Robust z-score: how far this week sits from the typical week, measured against normal week-to-week noise. ' +
    'Higher means more unusual. Informational only — the change threshold decides what gets flagged.'

// Frontend mirror of the backend SENSITIVITY_PRESETS. Selecting a preset applies these thresholds locally.
export const SENSITIVITY_PRESETS: Record<
    Exclude<PulseSensitivity, 'custom'>,
    { min_change_pct: number; robust_z_threshold: number }
> = {
    conservative: { min_change_pct: 0.4, robust_z_threshold: 3.5 },
    balanced: { min_change_pct: 0.25, robust_z_threshold: 3.5 },
    sensitive: { min_change_pct: 0.15, robust_z_threshold: 3.0 },
}
