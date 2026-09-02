import { createTrackedRE2 } from '~/common/utils/tracked-re2'

import { parseLogBodyForIngestion } from './log-body-parse'

export const PATTERN_VERSION = 4

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

export type MaskRuleName =
    | 'timestamp'
    | 'klogtime'
    | 'clftime'
    | 'ctime'
    | 'httpdate'
    | 'syslogtime'
    | 'uuid'
    | 'email'
    | 'host'
    | 'hex0x'
    | 'hex'
    | 'ipv4'
    | 'num'

export type MaskRule = {
    name: MaskRuleName
    pattern: string
    replacement: string
}

const MONTH = '(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
const WEEKDAY = '(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)'
const DAY_OF_MONTH = '(?:0?[1-9]|[12]\\d|3[01])'
const TIME_OF_DAY = '\\d{2}:\\d{2}:\\d{2}'

export const MASK_RULES: readonly MaskRule[] = [
    {
        name: 'timestamp',
        pattern: `\\b\\d{4}-\\d{2}-\\d{2}[T ]${TIME_OF_DAY}(?:[.,]\\d+)?(?:Z|[+-]\\d{2}:?\\d{2})?`,
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
        pattern: `\\b${letter}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\\d|3[01]) ${TIME_OF_DAY}(?:\\.\\d+)?`,
        replacement: `${letter}<KLOGTIME>`,
    })),
    // Date formats that spell the month or the weekday as a name. `\b\d+` masks the digits around
    // the name but cannot touch the name itself, so the name survives into the pattern as a literal:
    // one line splits into 12 patterns over a year, and into 7 over a week once a weekday is in it.
    // Each rule consumes the whole date, so the name leaves with it.
    //
    // The name also guards the match: nothing here claims a bare number followed by a time of day.
    //
    // Order matters between these rules and is asserted by the sequential-chain corpus. `ctime` and
    // `httpdate` open on a weekday and `syslogtime` opens on a month, so on a ctime line the month
    // rule starts later in the string. A single pass takes the leftmost match and drops the weekday,
    // but a rule-at-a-time chain would let the month rule cut the line first and strand the weekday.
    // Listing the weekday forms first makes both orders agree.
    {
        name: 'clftime',
        pattern: `\\b\\d{2}/${MONTH}/\\d{4}:${TIME_OF_DAY}(?: [+-]\\d{4})?`,
        replacement: '<TIMESTAMP>',
    },
    {
        name: 'ctime',
        pattern: `\\b${WEEKDAY} ${MONTH} {1,2}${DAY_OF_MONTH} ${TIME_OF_DAY}(?: [A-Z]{2,5})? \\d{4}`,
        replacement: '<TIMESTAMP>',
    },
    {
        name: 'httpdate',
        pattern: `\\b${WEEKDAY}, \\d{1,2} ${MONTH} \\d{4} ${TIME_OF_DAY}(?: GMT| UTC| [+-]\\d{4})?`,
        replacement: '<TIMESTAMP>',
    },
    {
        name: 'syslogtime',
        pattern: `\\b${MONTH} {1,2}${DAY_OF_MONTH} ${TIME_OF_DAY}`,
        replacement: '<TIMESTAMP>',
    },
    {
        name: 'uuid',
        pattern: '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}',
        replacement: '<UUID>',
    },
    { name: 'email', pattern: '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}', replacement: '<EMAIL>' },
    // The suffix list carries no `so` or `sh`. Both are real TLDs, but the rule cannot tell a host
    // from a filename, and shared object and shell script names reach it far more often than a
    // Somali or Saint Helenian domain does. With them in the list, `libssl.so` and `deploy.sh` both
    // mask to `<HOST>`, which merges lines that name different files.
    {
        name: 'host',
        pattern:
            '\\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?\\.){1,8}(?:ai|app|aws|bot|cloud|co|com|de|dev|eu|fr|gg|internal|io|jp|local|me|net|nl|org|tv|uk|us|xyz)\\b',
        replacement: '<HOST>',
    },
    { name: 'hex0x', pattern: '\\b0x[0-9a-fA-F]+\\b', replacement: '<HEX>' },
    // The order of the rules below is what keeps a plain digit run on `num`. A whole word of digits
    // reaches `num` before `hex` can see it, so an epoch, an id, or a byte count of 8 or more digits
    // stays `<N>`, and `hex` takes only the runs that hold a letter. Splitting `num` in two is how
    // "hex run containing a letter" reads without a lookahead, which RE2 does not have. `ipv4` leads
    // so a dotted quad stays one match instead of four numbers.
    { name: 'ipv4', pattern: '\\b\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\b', replacement: '<IP>' },
    { name: 'num', pattern: '\\b\\d+\\b', replacement: '<N>' },
    // Shortest hex run read as an identifier. Git short shas and container ids sit at 8 to 12 chars.
    { name: 'hex', pattern: '\\b[0-9a-fA-F]{8,}\\b', replacement: '<HEX>' },
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

/**
 * One zeroed counter per rule in `MASK_RULES`, which `klogtime` spreads over four of.
 *
 * Every result carries a full-width vector, including the bodies that fire no rule at all. A shorter
 * array would read as `undefined` to a caller that indexes by rule position, and reach a counter as
 * `NaN`.
 */
export const zeroRuleFires = (): number[] => new Array(MASK_RULES.length).fill(0)

/** Masks `input` and adds its rule hits into `ruleFires`, so several strings can share one array. */
function maskInto(input: string, ruleFires: number[]): string {
    return input.replace(MASK_COMBINED_RE, (...args: unknown[]): string => {
        for (let i = 0; i < MASK_RULES.length; i++) {
            if (args[i + 1] !== undefined) {
                ruleFires[i]++
                return MASK_RULES[i].replacement
            }
        }
        return args[0] as string
    })
}

export function maskString(input: string): MaskResult {
    const ruleFires = zeroRuleFires()
    return { masked: maskInto(input, ruleFires), ruleFires }
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

export const MESSAGE_KEYS = ['message', 'msg', 'event'] as const

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

/**
 * Keys go through the same mask rules as a message, because a key set is just as often built from
 * data: an object keyed by user id, host, or trace id otherwise emits one pattern per record, which
 * is the shape the key set exists to collapse.
 *
 * Deduplicating after the mask is what bounds such an object to a single key, and doing it before
 * the cap keeps the dropped-key count off the raw key count, because `+41` and `+42` are two
 * patterns for one shape.
 */
function jsonKeySetPattern(rawKeys: readonly string[]): { pattern: string; ruleFires: number[] } {
    const ruleFires = zeroRuleFires()
    const masked = new Set<string>()
    for (const key of rawKeys) {
        masked.add(maskInto(key, ruleFires))
    }

    const keys = [...masked].sort()
    const kept = keys.slice(0, KEY_SET_MAX_KEYS)
    const overflow = keys.length - kept.length
    return { pattern: `<JSON:${kept.join(',')}${overflow > 0 ? `,+${overflow}` : ''}>`, ruleFires }
}

export type PatternInputSelection =
    | { kind: 'empty'; bodyKind: PatternBodyKind; inputCapped: boolean }
    | { kind: 'mask'; input: string; bodyKind: PatternBodyKind; inputCapped: boolean }
    | {
          kind: 'pattern'
          pattern: string
          bodyKind: PatternBodyKind
          inputCapped: boolean
          ruleFires: number[]
          jsonKeyCount?: number
      }

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
                if (Array.isArray(parsed.value)) {
                    return { kind: 'pattern', pattern: JSON_ARRAY, bodyKind, inputCapped, ruleFires: zeroRuleFires() }
                }
                const rawKeys = Object.keys(parsed.value)
                const keySet = jsonKeySetPattern(rawKeys)
                return {
                    kind: 'pattern',
                    pattern: keySet.pattern,
                    bodyKind,
                    inputCapped,
                    ruleFires: keySet.ruleFires,
                    jsonKeyCount: rawKeys.length,
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
        return { pattern: '', bodyKind, inputCapped, maskedLength: 0, ruleFires: zeroRuleFires() }
    }

    if (selection.kind === 'pattern') {
        return {
            pattern: capOutput(selection.pattern),
            bodyKind,
            inputCapped,
            maskedLength: selection.pattern.length,
            ...(selection.jsonKeyCount === undefined ? {} : { jsonKeyCount: selection.jsonKeyCount }),
            ruleFires: selection.ruleFires,
        }
    }

    return { ...computeLogPattern(selection.input), bodyKind, inputCapped }
}
