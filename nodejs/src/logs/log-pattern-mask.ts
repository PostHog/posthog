/**
 * Replace the variable parts of a log body with placeholders so the remaining shape is a stable
 * pattern identity. One combined alternation regex, one pass; alternation order is rule priority.
 * Rules must stay RE2-safe (bodies are attacker-controlled); a test ratchet enforces this.
 */
import { createTrackedRE2 } from '~/common/utils/tracked-re2'

import { parseLogBodyForIngestion } from './log-body-parse'

/** A rule change re-keys every pattern, so bump this in the same commit as any rule change. */
export const PATTERN_VERSION = 1

export type MaskRuleName = 'timestamp' | 'uuid' | 'email' | 'hex0x' | 'hex' | 'ipv4' | 'num'

export type MaskRule = {
    name: MaskRuleName
    /** RE2-safe source with no capturing groups; the combined regex wraps it in one. */
    pattern: string
    replacement: string
}

/**
 * Order is load-bearing: `timestamp` and `ipv4` before `num`, `email` before anything claiming
 * part of an address. `num` drops the trailing `\b` on purpose so `7141ms` masks to `<N>ms`.
 */
export const MASK_RULES: readonly MaskRule[] = [
    {
        name: 'timestamp',
        pattern: '\\b\\d{4}-\\d{2}-\\d{2}[T ]\\d{2}:\\d{2}:\\d{2}(?:[.,]\\d+)?(?:Z|[+-]\\d{2}:?\\d{2})?',
        replacement: '<TIMESTAMP>',
    },
    {
        name: 'uuid',
        pattern: '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}',
        replacement: '<UUID>',
    },
    // Copied from `log-pii-scrub.ts` on purpose: sharing it would tie scrub edits to PATTERN_VERSION.
    { name: 'email', pattern: '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}', replacement: '<EMAIL>' },
    { name: 'hex0x', pattern: '\\b0x[0-9a-fA-F]+\\b', replacement: '<HEX>' },
    { name: 'hex', pattern: '\\b[0-9a-fA-F]{16,}\\b', replacement: '<HEX>' },
    { name: 'ipv4', pattern: '\\b\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\b', replacement: '<IP>' },
    { name: 'num', pattern: '\\b\\d+', replacement: '<N>' },
]

/** Bucket for JSON array bodies; key-set identity only applies to objects. */
export const JSON_ARRAY = '<JSON_ARRAY>'

/** Over the cap, the key-set pattern keeps the first keys after sorting and appends `,+N`. */
const KEY_SET_MAX_KEYS = 32

const MASK_COMBINED_RE = createTrackedRE2(
    MASK_RULES.map((rule) => `(${rule.pattern})`).join('|'),
    'g',
    'log-pattern-mask:combined'
)

export type MaskResult = {
    masked: string
    /** Match counts aligned with `MASK_RULES` by index. */
    ruleFires: number[]
}

export function maskString(input: string): MaskResult {
    const ruleFires: number[] = new Array(MASK_RULES.length).fill(0)
    const masked = input.replace(MASK_COMBINED_RE, (...args: unknown[]): string => {
        for (let i = 0; i < MASK_RULES.length; i++) {
            if (args[i + 1] !== undefined) {
                ruleFires[i]++
                return MASK_RULES[i].replacement
            }
        }
        return args[0] as string
    })
    return { masked, ruleFires }
}

export type PatternBodyKind = 'empty' | 'invalid_json' | 'json_object_or_array' | 'json_string' | 'primitive'

export type LogPatternResult = {
    /** Masked, then truncated to `maxOutputChars`. */
    pattern: string
    bodyKind: PatternBodyKind
    /** True when the body exceeded `maxInputChars` and was cut before masking. */
    inputCapped: boolean
    /** Masked length before truncation. */
    maskedLength: number
    /** Top-level key count when the pattern is a key-set identity; absent otherwise. */
    jsonKeyCount?: number
    ruleFires: number[]
}

const MESSAGE_KEYS = ['message', 'msg', 'event'] as const

function extractJsonMessage(value: object): string | null {
    if (Array.isArray(value)) {
        return null
    }
    for (const key of MESSAGE_KEYS) {
        const candidate = (value as Record<string, unknown>)[key]
        if (typeof candidate === 'string') {
            return candidate
        }
    }
    return null
}

/**
 * Sorted top-level key list as a deterministic identity for message-less JSON objects: sort so
 * source key order does not matter, top-level only, keys verbatim. Keys are schema, not values,
 * so the mask rules never run on this pattern.
 */
function jsonKeySetPattern(value: object): string {
    const keys = Object.keys(value).sort()
    const kept = keys.slice(0, KEY_SET_MAX_KEYS)
    const overflow = keys.length - kept.length
    return `<JSON:${kept.join(',')}${overflow > 0 ? `,+${overflow}` : ''}>`
}

/**
 * Cap the input, mask, then truncate the masked result. Mask before truncate so masking shortens
 * the line first and more real content survives the cut.
 */
export function computeLogPattern(
    body: string | null | undefined,
    maxInputChars: number,
    maxOutputChars: number
): LogPatternResult {
    // Nullish, not `=== null`: a record decoded from a schema with no `body` field yields undefined.
    // `''` belongs here too — `parseLogBodyForIngestion` calls it invalid JSON, which would file a
    // body carrying no pattern on the prose side of the structured-versus-prose split.
    if (body === null || body === undefined || body === '') {
        return { pattern: '', bodyKind: 'empty', inputCapped: false, maskedLength: 0, ruleFires: [] }
    }

    // Cap before parsing so the ceiling guards the JSON.parse too; a capped JSON body parses as prose.
    const inputCapped = body.length > maxInputChars
    const cappedBody = inputCapped ? body.slice(0, maxInputChars) : body
    const parsed = parseLogBodyForIngestion(cappedBody)
    const bodyKind: PatternBodyKind = parsed.kind === 'json_primitive' ? 'primitive' : parsed.kind

    let maskInput: string
    switch (parsed.kind) {
        case 'empty':
            maskInput = ''
            break
        case 'json_object_or_array': {
            const message = extractJsonMessage(parsed.value)
            if (message === null) {
                const isArray = Array.isArray(parsed.value)
                const pattern = isArray ? JSON_ARRAY : jsonKeySetPattern(parsed.value)
                return {
                    pattern: pattern.length > maxOutputChars ? pattern.slice(0, maxOutputChars) : pattern,
                    bodyKind,
                    inputCapped,
                    maskedLength: pattern.length,
                    ...(isArray ? {} : { jsonKeyCount: Object.keys(parsed.value).length }),
                    ruleFires: [],
                }
            }
            maskInput = message
            break
        }
        case 'json_string':
            maskInput = parsed.value
            break
        case 'json_primitive':
            maskInput = cappedBody
            break
        case 'invalid_json':
            maskInput = parsed.raw
            break
    }

    const { masked, ruleFires } = maskString(maskInput)
    return {
        pattern: masked.length > maxOutputChars ? masked.slice(0, maxOutputChars) : masked,
        bodyKind,
        inputCapped,
        maskedLength: masked.length,
        ruleFires,
    }
}
