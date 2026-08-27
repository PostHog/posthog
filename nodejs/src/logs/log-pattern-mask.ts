import type RE2 from 're2'

import { createTrackedRE2 } from '~/common/utils/tracked-re2'

import { parseLogBodyForIngestion } from './log-body-parse'

export const PATTERN_VERSION = 4

export type MaskRuleName =
    | 'timestamp'
    | 'klogtime'
    | 'awskey'
    | 'bearer'
    | 'jwt'
    | 'stripe'
    | 'aikey'
    | 'posthogkey'
    | 'ghtoken'
    | 'slacktoken'
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
    // Credential formats, ahead of every rule that would otherwise chew a token into pieces. `hex`
    // and `num` both bite into a key body, and once they do the prefix is stranded next to a run of
    // placeholders and the credential is neither redacted nor recognizable.
    //
    // The pattern is copied into `logs_pattern_buckets`, so a secret reaching it is stored twice, on
    // two retention clocks. The PII scrub that would otherwise catch some of these runs earlier in
    // the pipeline but is opt-in per team, so a team that has not enabled it gets whatever these
    // rules catch and nothing else.
    //
    // Every rule anchors on a vendor-assigned prefix or a structural marker, which is what keeps
    // them from swallowing ordinary words the way a general identifier rule would. The length floors
    // do the same job for the two prefixes that are also English: without them `Bearer token missing`
    // masks as a credential.
    //
    // Deliberately absent: Stripe `pk_` and PostHog `phc_`. Both are publishable keys, meant to sit
    // in client-side code, so masking them hides which project a line belongs to and protects
    // nothing. `ph[xsar]_` covers the personal, project-secret, OAuth-access and refresh keys only.
    { name: 'awskey', pattern: '\\b(?:A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z2-7]{16}\\b', replacement: '<AWS_KEY>' },
    { name: 'bearer', pattern: '(?i:Bearer\\s+)[-A-Za-z0-9._~+/]{16,}=*', replacement: 'Bearer <TOKEN>' },
    // Both segments must start `eyJ` — base64url for `{"`, so header and payload each decode to the
    // start of a JSON object. One `eyJ` alone matches any base64-encoded JSON.
    //
    // Each segment also carries a minimum length. RE2 matches in linear time, but `replace` with the
    // global flag restarts at every position, so an unbounded tail turns a body of `eyJ.eyJ.eyJ...`
    // into quadratic work — measured at 258 times the cost of an ordinary line, from input a
    // customer controls.
    {
        name: 'jwt',
        pattern: '\\beyJ[A-Za-z0-9_-]{8,}\\.eyJ[A-Za-z0-9_-]{8,}\\.[A-Za-z0-9_-]{4,}',
        replacement: '<JWT>',
    },
    { name: 'stripe', pattern: '\\b[sr]k_(?:live|test)_[A-Za-z0-9]{20,}\\b', replacement: '<STRIPE_KEY>' },
    // The two vendor shapes are spelled out rather than sharing one tail, because a tail that admits
    // the hyphen both matches any kebab-case token starting `sk-` (`sk-cluster-prod-eu-west-1`) and
    // gives `sk-sk-sk-...` one enormous run to chew through.
    {
        name: 'aikey',
        pattern: '\\bsk-(?:ant-api\\d{2}-[A-Za-z0-9_-]{16,}|(?:proj-)?[A-Za-z0-9]{20,})\\b',
        replacement: '<AI_KEY>',
    },
    { name: 'posthogkey', pattern: '\\bph[xsar]_[A-Za-z0-9]{20,}\\b', replacement: '<POSTHOG_KEY>' },
    { name: 'ghtoken', pattern: '\\bgh[pousr]_[A-Za-z0-9]{36}\\b', replacement: '<GH_TOKEN>' },
    { name: 'slacktoken', pattern: '\\bxox[baprs]-[A-Za-z0-9-]{10,}\\b', replacement: '<SLACK_TOKEN>' },
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

const KEY_SET_MAX_KEYS = 32

const CREDENTIAL_RULES: ReadonlySet<MaskRuleName> = new Set([
    'awskey',
    'bearer',
    'jwt',
    'stripe',
    'aikey',
    'posthogkey',
    'ghtoken',
    'slacktoken',
])

// Two passes, because every branch costs per character even when it matches nothing: carrying the
// credential rules on every line roughly doubles the cost of masking an ordinary one. Almost no
// line holds a credential, so a literal prefilter picks the cheaper pass for nearly all of them.
//
// Every credential rule needs a fixed literal to be present before it can match, and the prefilter
// is the union of those literals, so the cheap pass can only skip a rule that could not have fired.
// It is case-insensitive where the rules are not, which makes it a superset and keeps that true.
// The per-rule tests below are what hold it: a rule whose literal is missing here stops masking its
// own fixture.
const CREDENTIAL_PREFILTER_RE = createTrackedRE2(
    '(?i:bearer|eyJ|A3T|AKIA|ASIA|ABIA|ACCA|sk-|sk_|rk_|ph[xsar]_|gh[pousr]_|xox)',
    undefined,
    'log-pattern-mask:credential-prefilter'
)

// Each pass carries the MASK_RULES index of every rule it runs, so a fire is attributed to the same
// slot whichever pass produced it. Capture groups are positional, so the group number and the rule
// index part company as soon as one pass omits a rule.
const ALL_RULE_INDEXES = MASK_RULES.map((_, index) => index)
const CHEAP_RULE_INDEXES = MASK_RULES.flatMap((rule, index) => (CREDENTIAL_RULES.has(rule.name) ? [] : [index]))

const combinedFor = (indexes: number[], source: string): RE2 =>
    createTrackedRE2(indexes.map((index) => `(${MASK_RULES[index].pattern})`).join('|'), 'g', source)

const MASK_COMBINED_RE = combinedFor(ALL_RULE_INDEXES, 'log-pattern-mask:combined')
const MASK_CHEAP_RE = combinedFor(CHEAP_RULE_INDEXES, 'log-pattern-mask:no-credentials')

export type MaskResult = {
    masked: string
    ruleFires: number[]
}

export function maskString(input: string): MaskResult {
    const ruleFires: number[] = new Array(MASK_RULES.length).fill(0)
    // `CREDENTIAL_PREFILTER_RE` carries no global flag, so `test` holds no position between calls.
    const mayHoldCredential = CREDENTIAL_PREFILTER_RE.test(input)
    const indexes = mayHoldCredential ? ALL_RULE_INDEXES : CHEAP_RULE_INDEXES
    const combined = mayHoldCredential ? MASK_COMBINED_RE : MASK_CHEAP_RE
    const masked = input.replace(combined, (...args: unknown[]): string => {
        for (let group = 0; group < indexes.length; group++) {
            if (args[group + 1] !== undefined) {
                const index = indexes[group]
                ruleFires[index]++
                return MASK_RULES[index].replacement
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

function jsonKeySetPattern(value: object): string {
    const keys = Object.keys(value).sort()
    const kept = keys.slice(0, KEY_SET_MAX_KEYS)
    const overflow = keys.length - kept.length
    return `<JSON:${kept.join(',')}${overflow > 0 ? `,+${overflow}` : ''}>`
}

export function computeLogPattern(
    body: string | null | undefined,
    maxInputChars: number,
    maxOutputChars: number
): LogPatternResult {
    if (body === null || body === undefined || body === '') {
        return { pattern: '', bodyKind: 'empty', inputCapped: false, maskedLength: 0, ruleFires: [] }
    }

    const inputCapped = body.length > maxInputChars
    const cappedBody = inputCapped ? body.slice(0, maxInputChars) : body
    const parsed = parseLogBodyForIngestion(cappedBody)
    const bodyKind: PatternBodyKind =
        parsed.kind === 'json_primitive' ? 'primitive' : parsed.kind === 'invalid_json' ? 'plaintext' : parsed.kind

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
