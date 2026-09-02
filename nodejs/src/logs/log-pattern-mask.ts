import { createTrackedRE2 } from '~/common/utils/tracked-re2'

import { parseLogBodyForIngestion } from './log-body-parse'

export const PATTERN_VERSION = 3

/**
 * Everything here shapes the emitted pattern, so it sits inside `PATTERN_VERSION`: two records may
 * only be grouped by `pattern` when they carry the same version.
 *
 * These are constants rather than config for that reason. A per-pod override would let two pods stamp
 * one version onto differently shaped patterns, which no consumer could detect. The shape-safe
 * operational lever is `LOGS_PATTERN_MASKING_ENABLED_TEAMS`, which stops masking instead of changing it.
 *
 * `computeLogPattern` takes no caps argument, so there is no override path to reach at all. `readonly`
 * states the intent to the compiler and `Object.freeze` holds it at runtime, because a caller reaching
 * this object through an `any` would otherwise reshape every pattern under an unchanged version.
 */
export type PatternCaps = {
    /** Ceiling on the body chars fed to the masker; longer bodies are cut first (CPU guard). */
    readonly maxInputChars: number
    /** Truncation applied to the masked pattern, after masking, so more real content survives the cut. */
    readonly maxOutputChars: number
}

export const PATTERN_CAPS: PatternCaps = Object.freeze({
    maxInputChars: 8192,
    maxOutputChars: 1024,
})

export type MaskRuleName = 'timestamp' | 'klogtime' | 'uuid' | 'email' | 'host' | 'hex0x' | 'hex' | 'ipv4' | 'num'

export type MaskRule = {
    name: MaskRuleName
    pattern: string
    replacement: string
}

export const MASK_RULES: readonly MaskRule[] = [
    {
        name: 'timestamp',
        pattern: '\\b\\d{4}-\\d{2}-\\d{2}[T ]\\d{2}:\\d{2}:\\d{2}(?:[.,]\\d+)?(?:Z|[+-]\\d{2}:?\\d{2})?',
        replacement: '<TIMESTAMP>',
    },
    // klog / glog headers ("I0827 11:39:40.307946") carry no year and no separators, so the
    // timestamp rule above misses them and `\b\d+` cannot reach the date either — there is no word
    // boundary between the severity letter and the digits, so the date survives as a literal and
    // the pattern changes every midnight.
    //
    // One rule per severity letter, rather than one rule with a lookbehind. The letter is content,
    // not a variable, so it has to survive into the output; replacements are constant strings, so
    // the only way to keep it is to consume it and write it back. Lookbehind and backreferences are
    // both unavailable — RE2 lacks the first, and the rule-fire attribution in MASK_COMBINED_RE
    // indexes capture groups positionally, so a rule may not add one.
    //
    // The letter also guards the match. Without it, `\d{4} \d{2}:\d{2}:\d{2}` would claim any count
    // followed by a time of day.
    //
    // The date is spelled out as a real MMDD rather than `\d{4}`, because the letter alone is a weak
    // guard: the rule reaches text that `\b\d+` cannot (there is no boundary between the letter and
    // the digits), so a bare `\d{4}` masks any letter-prefixed 4-digit token that happens to precede
    // a time — collapsing `E2024 10:20:30` and `E2025 10:20:30`, which are distinct today. A month of
    // 01-12 and a day of 01-31 rejects those while accepting every date klog can print. The match
    // cannot be anchored to the line start instead: Kubernetes CRI lines carry a container prefix
    // ("<time> stderr F I0827 ..."), so the header is mid-string in the most common real source.
    ...(['I', 'W', 'E', 'F'] as const).map((letter) => ({
        name: 'klogtime' as const,
        pattern: `\\b${letter}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\\d|3[01]) \\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?`,
        replacement: `${letter}<KLOGTIME>`,
    })),
    {
        name: 'uuid',
        pattern: '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}',
        replacement: '<UUID>',
    },
    { name: 'email', pattern: '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}', replacement: '<EMAIL>' },
    {
        name: 'host',
        pattern:
            '\\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?\\.){1,8}(?:ai|app|aws|bot|cloud|co|com|de|dev|eu|fr|gg|internal|io|jp|local|me|net|nl|org|sh|so|tv|uk|us|xyz)\\b',
        replacement: '<HOST>',
    },
    { name: 'hex0x', pattern: '\\b0x[0-9a-fA-F]+\\b', replacement: '<HEX>' },
    { name: 'hex', pattern: '\\b[0-9a-fA-F]{16,}\\b', replacement: '<HEX>' },
    { name: 'ipv4', pattern: '\\b\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\b', replacement: '<IP>' },
    { name: 'num', pattern: '\\b\\d+', replacement: '<N>' },
]

export const JSON_ARRAY = '<JSON_ARRAY>'

export const KEY_SET_MAX_KEYS = 32

const MASK_COMBINED_RE = createTrackedRE2(
    MASK_RULES.map((rule) => `(${rule.pattern})`).join('|'),
    'g',
    'log-pattern-mask:combined'
)

export type MaskResult = {
    masked: string
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

export type PatternBodyKind = 'empty' | 'plaintext' | 'json_object_or_array' | 'json_string' | 'primitive'

export type LogPatternResult = {
    pattern: string
    bodyKind: PatternBodyKind
    inputCapped: boolean
    maskedLength: number
    jsonKeyCount?: number
    ruleFires: number[]
}

function extractJsonMessage(value: object, messageKeys: readonly string[]): string | null {
    if (Array.isArray(value)) {
        return null
    }
    for (const key of messageKeys) {
        const candidate = (value as Record<string, unknown>)[key]
        if (typeof candidate === 'string') {
            return candidate
        }
    }
    return null
}

const capOutput = (pattern: string): string =>
    pattern.length > PATTERN_CAPS.maxOutputChars ? pattern.slice(0, PATTERN_CAPS.maxOutputChars) : pattern

function jsonKeySetPattern(value: object): string {
    const keys = Object.keys(value).sort()
    const kept = keys.slice(0, KEY_SET_MAX_KEYS)
    const overflow = keys.length - kept.length
    return `<JSON:${kept.join(',')}${overflow > 0 ? `,+${overflow}` : ''}>`
}

export type PatternInputSelection =
    | { kind: 'empty'; bodyKind: PatternBodyKind; inputCapped: boolean }
    | { kind: 'mask'; input: string; bodyKind: PatternBodyKind; inputCapped: boolean }
    | { kind: 'pattern'; pattern: string; bodyKind: PatternBodyKind; inputCapped: boolean; jsonKeyCount?: number }

export function selectPatternInput(
    body: string | null | undefined,
    messageKeys: readonly string[]
): PatternInputSelection {
    if (body === null || body === undefined || body === '') {
        return { kind: 'empty', bodyKind: 'empty', inputCapped: false }
    }

    const inputCapped = body.length > PATTERN_CAPS.maxInputChars
    const cappedBody = inputCapped ? body.slice(0, PATTERN_CAPS.maxInputChars) : body
    const parsed = parseLogBodyForIngestion(cappedBody)
    const bodyKind: PatternBodyKind =
        parsed.kind === 'json_primitive' ? 'primitive' : parsed.kind === 'invalid_json' ? 'plaintext' : parsed.kind

    switch (parsed.kind) {
        case 'empty':
            return { kind: 'mask', input: '', bodyKind, inputCapped }
        case 'json_object_or_array': {
            const message = extractJsonMessage(parsed.value, messageKeys)
            if (message === null) {
                const isArray = Array.isArray(parsed.value)
                return {
                    kind: 'pattern',
                    pattern: isArray ? JSON_ARRAY : jsonKeySetPattern(parsed.value),
                    bodyKind,
                    inputCapped,
                    ...(isArray ? {} : { jsonKeyCount: Object.keys(parsed.value).length }),
                }
            }
            return { kind: 'mask', input: message, bodyKind, inputCapped }
        }
        case 'json_string':
            return { kind: 'mask', input: parsed.value, bodyKind, inputCapped }
        case 'json_primitive':
            return { kind: 'mask', input: cappedBody, bodyKind, inputCapped }
        case 'invalid_json':
            return { kind: 'mask', input: parsed.raw, bodyKind, inputCapped }
    }
}

export type MaskedPattern = {
    pattern: string
    maskedLength: number
    ruleFires: number[]
}

export function computeLogPattern(input: string): MaskedPattern {
    const { masked, ruleFires } = maskString(input)
    return { pattern: capOutput(masked), maskedLength: masked.length, ruleFires }
}

export function buildLogPattern(body: string | null | undefined, messageKeys: readonly string[]): LogPatternResult {
    const selection = selectPatternInput(body, messageKeys)
    const { bodyKind, inputCapped } = selection

    if (selection.kind === 'empty') {
        return { pattern: '', bodyKind, inputCapped, maskedLength: 0, ruleFires: [] }
    }

    if (selection.kind === 'pattern') {
        return {
            pattern: capOutput(selection.pattern),
            bodyKind,
            inputCapped,
            maskedLength: selection.pattern.length,
            ...(selection.jsonKeyCount === undefined ? {} : { jsonKeyCount: selection.jsonKeyCount }),
            ruleFires: [],
        }
    }

    return { ...computeLogPattern(selection.input), bodyKind, inputCapped }
}
