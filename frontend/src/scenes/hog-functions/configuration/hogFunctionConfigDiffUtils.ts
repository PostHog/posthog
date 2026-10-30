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
    /** How the field's display text was produced — drives the diff viewer's syntax highlighting. */
    kind: 'json' | 'text'
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

/**
 * Per-side character cap — a larger value collapses to the +/- stat summary in the card. The diff
 * viewer hides unchanged regions, so this is a safety valve against pathological payloads, not a
 * render budget.
 */
export const MAX_DIFF_FIELD_CHARS = 50_000

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

/** A mapping's own inputs carry secrets exactly like top-level inputs do; redact each in place. */
function redactMappingSecrets(value: unknown): unknown {
    if (!Array.isArray(value)) {
        return value
    }
    return value.map((mapping) => {
        if (!mapping || typeof mapping !== 'object') {
            return mapping
        }
        const { inputs, inputs_schema } = mapping as {
            inputs?: Record<string, CyclotronJobInputType>
            inputs_schema?: CyclotronJobInputSchemaType[]
        }
        return inputs ? { ...mapping, inputs: redactSecretHogFunctionInputs(inputs, inputs_schema ?? []) } : mapping
    })
}

/**
 * Only the current side can hold user secrets (a freshly typed secret is cleartext in form state);
 * redact it by schema before the value ever reaches the rendered card. The proposed side is
 * agent-authored, so showing it is not a leak, and redacting it would hide a real change to a
 * secret input. Secrets live in top-level `inputs` and in each mapping's own `inputs`.
 */
function redactCurrentValue(field: string, current: Record<string, unknown>): unknown {
    if (field === 'inputs') {
        return redactSecretHogFunctionInputs(
            (current.inputs ?? {}) as Record<string, CyclotronJobInputType>,
            (current.inputs_schema ?? []) as CyclotronJobInputSchemaType[]
        )
    }
    if (field === 'mappings') {
        return redactMappingSecrets(current.mappings)
    }
    return current[field]
}

/**
 * Builds a field-level diff of a proposed `cdp-functions-partial-update` against the current hog function
 * config. Only fields present in `proposed` are considered (a partial update leaves the rest untouched);
 * unchanged fields are dropped. Pure and dependency-light so it's cheap to unit-test.
 */
export function buildHogFunctionConfigDiff(
    current: Record<string, unknown>,
    proposed: Record<string, unknown>,
    fields: DiffableField[] = DIFFABLE_FIELDS
): HogFunctionFieldDiff[] {
    const diffs: HogFunctionFieldDiff[] = []
    for (const { field, label, kind, normalize } of fields) {
        if (!(field in proposed)) {
            continue
        }
        const rawCurrent = redactCurrentValue(field, current)
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
            kind,
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

/** Mirrors DRAFT_CONTENT_FIELDS in products/cdp/backend/api/hog_function.py. Keep the two lists in sync. */
export const HOG_FUNCTION_DRAFT_CONTENT_FIELDS = ['hog', 'inputs_schema', 'inputs', 'filters', 'mappings', 'masking']

export function hogFunctionFieldLabel(field: string): string {
    return DIFFABLE_FIELDS.find((diffable) => diffable.field === field)?.label ?? field
}

const DERIVED_FILTER_KEYS = ['bytecode', 'bytecode_error', 'bytecode_contract', 'transpiled']
const DERIVED_INPUT_KEYS = ['bytecode', 'bytecode_contract', 'transpiled', 'order']

// Both sides of a draft diff come from the API, so `comparableContent` already strips derived input
// keys. Value-only inputs would hide a templating change.
const DRAFT_DIFFABLE_FIELDS: DiffableField[] = DIFFABLE_FIELDS.filter(({ field }) =>
    HOG_FUNCTION_DRAFT_CONTENT_FIELDS.includes(field)
).map((diffable) => ({ ...diffable, normalize: undefined }))

function withoutKeys(value: unknown, keys: string[]): unknown {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
        return value
    }
    return Object.fromEntries(Object.entries(value as Record<string, unknown>).filter(([key]) => !keys.includes(key)))
}

function comparableInputs(inputs: unknown, inputsSchema: unknown): unknown {
    if (!inputs || typeof inputs !== 'object') {
        return inputs
    }
    const redacted = redactSecretHogFunctionInputs(
        inputs as Record<string, CyclotronJobInputType>,
        (inputsSchema ?? []) as CyclotronJobInputSchemaType[]
    )
    return Object.fromEntries(
        Object.entries(redacted).map(([key, entry]) => {
            // The server treats a missing `templating` as Hog, and an agent edit often sends values only.
            const derived = entry?.templating === 'hog' ? [...DERIVED_INPUT_KEYS, 'templating'] : DERIVED_INPUT_KEYS
            return [key, withoutKeys(entry, derived)]
        })
    )
}

/**
 * Mirrors `comparable_content` in products/cdp/backend/api/hog_function.py: drops the values the
 * server compiles from the config (bytecode, transpiled JS, input ordering), so a recompile does not
 * read as a change. Secrets are redacted on both sides, because the API masks them anyway.
 */
function comparableContent(content: Record<string, unknown>): Record<string, unknown> {
    const mappings = content.mappings
    return {
        ...content,
        inputs: comparableInputs(content.inputs, content.inputs_schema),
        filters: withoutKeys(content.filters, DERIVED_FILTER_KEYS),
        masking: withoutKeys(content.masking, ['bytecode']),
        mappings: Array.isArray(mappings)
            ? mappings.map((mapping) =>
                  mapping && typeof mapping === 'object'
                      ? {
                            ...mapping,
                            filters: withoutKeys(mapping.filters, DERIVED_FILTER_KEYS),
                            inputs: comparableInputs(mapping.inputs, mapping.inputs_schema),
                        }
                      : mapping
              )
            : mappings,
    }
}

/** Field-level diff of a function's staged draft against its live config. */
export function buildHogFunctionDraftDiff(
    live: Record<string, unknown>,
    draft: Record<string, unknown>
): HogFunctionFieldDiff[] {
    return buildHogFunctionConfigDiff(comparableContent(live), comparableContent(draft), DRAFT_DIFFABLE_FIELDS)
}
