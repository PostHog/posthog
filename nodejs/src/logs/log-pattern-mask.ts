import { createTrackedRE2 } from '~/common/utils/tracked-re2'

import { parseLogBodyForIngestion } from './log-body-parse'

export const PATTERN_VERSION = 2

export type MaskRuleName = 'timestamp' | 'uuid' | 'email' | 'host' | 'hex0x' | 'hex' | 'ipv4' | 'num'

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
