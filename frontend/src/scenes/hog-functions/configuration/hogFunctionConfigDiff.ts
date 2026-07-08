import type { CyclotronJobInputSchemaType, CyclotronJobInputType } from '~/types'

import { getDiffStats } from 'products/posthog_ai/frontend/api/tools'

import { redactSecretHogFunctionInputs } from '../hog-function-utils'

/** How a proposed field relates to the current config: newly set, cleared, or a value change. */
export type HogFunctionFieldStatus = 'added' | 'removed' | 'changed'

/** One field the agent's `cdp-functions-partial-update` proposes to change, resolved against current config. */
export interface HogFunctionFieldDiff {
    field: string
    /** Sentence-case field label, e.g. 'Filters', 'Source code'. */
    label: string
    status: HogFunctionFieldStatus
    /** Pretty-printed current value (empty when `added`). */
    currentText: string
    /** Pretty-printed proposed value (empty when `removed`). */
    proposedText: string
    /** Line-level added/removed counts, from the surface's shared `getDiffStats`. */
    added: number
    removed: number
    /** True when either side exceeds the render cap — the card shows the stat summary, not the content. */
    truncated: boolean
}

interface DiffableField {
    field: string
    label: string
    kind: 'json' | 'text'
    /** Optional projection applied to both sides before diffing, to drop server-only noise. */
    normalize?: (value: unknown) => unknown
}

/**
 * `inputs` entries carry server-computed noise (bytecode / order / templating) in the live form config
 * that the MCP tool strips from its payload. Compare value-only maps so an unchanged input doesn't read
 * as a change.
 */
function normalizeInputs(value: unknown): unknown {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
        return value
    }
    const out: Record<string, unknown> = {}
    for (const [key, entry] of Object.entries(value as Record<string, unknown>)) {
        out[key] = entry && typeof entry === 'object' && 'value' in entry ? (entry as { value: unknown }).value : entry
    }
    return out
}

// The subset of a hog function's config that `cdp-functions-partial-update` can touch and that reads
// meaningfully as a diff. Order is display order in the card.
const DIFFABLE_FIELDS: DiffableField[] = [
    { field: 'name', label: 'Name', kind: 'text' },
    { field: 'description', label: 'Description', kind: 'text' },
    { field: 'enabled', label: 'Enabled', kind: 'text' },
    { field: 'hog', label: 'Source code', kind: 'text' },
    { field: 'filters', label: 'Filters', kind: 'json' },
    { field: 'inputs', label: 'Inputs', kind: 'json', normalize: normalizeInputs },
    { field: 'inputs_schema', label: 'Inputs schema', kind: 'json' },
    { field: 'mappings', label: 'Mappings', kind: 'json' },
    { field: 'masking', label: 'Masking', kind: 'json' },
]

/** Per-side character cap — a larger value collapses to the +/- stat summary in the card. */
export const MAX_DIFF_FIELD_CHARS = 4000

function isEmptyValue(value: unknown): boolean {
    if (value == null || value === '') {
        return true
    }
    if (Array.isArray(value)) {
        return value.length === 0
    }
    if (typeof value === 'object') {
        return Object.keys(value as Record<string, unknown>).length === 0
    }
    return false
}

function toDisplayText(value: unknown, kind: DiffableField['kind']): string {
    if (value == null) {
        return ''
    }
    if (kind === 'text') {
        return typeof value === 'string' ? value : String(value)
    }
    try {
        return JSON.stringify(value, null, 2)
    } catch {
        return String(value)
    }
}

/**
 * Builds a field-level diff of a proposed `cdp-functions-partial-update` against the current hog function
 * config. Only fields present in `proposed` are considered (a partial update leaves the rest untouched);
 * unchanged fields are dropped. Pure and dependency-light so it's cheap to unit-test.
 */
export function buildHogFunctionConfigDiff(
    current: Record<string, unknown>,
    proposed: Record<string, unknown>
): HogFunctionFieldDiff[] {
    const diffs: HogFunctionFieldDiff[] = []
    for (const { field, label, kind, normalize } of DIFFABLE_FIELDS) {
        if (!(field in proposed)) {
            continue
        }
        // Only the current side can hold user secrets (a freshly typed secret is cleartext in form
        // state); redact it by schema before the value ever reaches the rendered card. The proposed
        // side is agent-authored, so showing it is not a leak, and redacting it would hide a real
        // change to a secret input.
        const rawCurrent =
            field === 'inputs'
                ? redactSecretHogFunctionInputs(
                      (current.inputs ?? {}) as Record<string, CyclotronJobInputType>,
                      (current.inputs_schema ?? []) as CyclotronJobInputSchemaType[]
                  )
                : current[field]
        const currentValue = normalize ? normalize(rawCurrent) : rawCurrent
        const proposedValue = normalize ? normalize(proposed[field]) : proposed[field]
        const currentText = toDisplayText(currentValue, kind)
        const proposedText = toDisplayText(proposedValue, kind)
        if (currentText === proposedText) {
            continue
        }
        const currentEmpty = isEmptyValue(currentValue)
        const proposedEmpty = isEmptyValue(proposedValue)
        const status: HogFunctionFieldStatus =
            currentEmpty && !proposedEmpty ? 'added' : !currentEmpty && proposedEmpty ? 'removed' : 'changed'
        const { added, removed } = getDiffStats(currentText, proposedText)
        diffs.push({
            field,
            label,
            status,
            currentText,
            proposedText,
            added,
            removed,
            truncated: currentText.length > MAX_DIFF_FIELD_CHARS || proposedText.length > MAX_DIFF_FIELD_CHARS,
        })
    }
    return diffs
}
