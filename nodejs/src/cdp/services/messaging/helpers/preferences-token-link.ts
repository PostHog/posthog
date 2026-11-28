import { parseJSON } from '~/common/utils/json-parse'

import { PosthogJwtAudience } from '../../../utils/jwt-utils'

const PERCENT = 0x25
const DOT = 0x2e
const ASCII_LIMIT = 0x80

const isWhitespaceOrControl = (code: number): boolean => code <= 0x20 || code === 0x7f

const hexDigitValue = (code: number): number => {
    if (code >= 0x30 && code <= 0x39) {
        return code - 0x30
    }
    const lower = code | 0x20
    return lower >= 0x61 && lower <= 0x66 ? lower - 0x61 + 10 : -1
}

const isBase64UrlChar = (code: number): boolean =>
    (code >= 0x30 && code <= 0x39) ||
    (code >= 0x41 && code <= 0x5a) ||
    (code >= 0x61 && code <= 0x7a) ||
    code === 0x2d ||
    code === 0x5f

const decodableEscapeAtEnd = (chars: number[]): number | undefined => {
    const length = chars.length
    if (length < 3 || chars[length - 3] !== PERCENT) {
        return undefined
    }
    const high = hexDigitValue(chars[length - 2])
    const low = hexDigitValue(chars[length - 1])
    if (high < 0 || low < 0) {
        return undefined
    }
    const code = high * 16 + low
    return code < ASCII_LIMIT ? code : undefined
}

const appendDecoding = (chars: number[], code: number): void => {
    let next: number | undefined = code
    while (next !== undefined && !isWhitespaceOrControl(next)) {
        chars.push(next)
        next = decodableEscapeAtEnd(chars)
        if (next !== undefined) {
            chars.length -= 3
        }
    }
}

const fullyDecodedChars = (link: string): number[] => {
    const chars: number[] = []
    for (let index = 0; index < link.length; index++) {
        appendDecoding(chars, link.charCodeAt(index))
    }
    return chars
}

const isPreferencesAudience = (audience: unknown): boolean =>
    audience === PosthogJwtAudience.SUBSCRIPTION_PREFERENCES ||
    (Array.isArray(audience) && audience.includes(PosthogJwtAudience.SUBSCRIPTION_PREFERENCES))

const isPreferencesPayload = (segment: number[]): boolean => {
    const json = Buffer.from(Buffer.from(segment).toString('latin1'), 'base64url')
    if (json[0] !== 0x7b) {
        return false
    }
    try {
        const payload: unknown = parseJSON(json.toString('utf8'))
        return (
            typeof payload === 'object' && payload !== null && isPreferencesAudience((payload as { aud?: unknown }).aud)
        )
    } catch {
        return false
    }
}

const runHoldsPreferencesJwt = (segments: number[][]): boolean => {
    for (let index = 1; index < segments.length - 1; index++) {
        const [header, payload, signature] = segments.slice(index - 1, index + 2)
        if (header.length && payload.length && signature.length && isPreferencesPayload(payload)) {
            return true
        }
    }
    return false
}

export const carriesPreferencesToken = (link: string): boolean => {
    let segments: number[][] = [[]]
    for (const code of [...fullyDecodedChars(link), -1]) {
        if (isBase64UrlChar(code)) {
            segments[segments.length - 1].push(code)
        } else if (code === DOT) {
            segments.push([])
        } else {
            if (runHoldsPreferencesJwt(segments)) {
                return true
            }
            segments = [[]]
        }
    }
    return false
}
