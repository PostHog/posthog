import type { BeforeSendFn, CapturedNetworkRequest } from 'posthog-js'

const MARKER = 'metricVariables'
// The options requests of dashboard variables carry queries and selected values, and return query results.
const VARIABLE_OPTIONS_PATH = '/metrics/variable_options'

/** A URL that holds metric variables, in any parameter or encoding, keeps only its path, so the queries, options and
 * selected values of the variables stay out of analytics. Other text that holds them is dropped. */
export function redactMetricVariableUrl(text: string): string {
    if (!text.includes(MARKER)) {
        return text
    }
    if (text.startsWith('/') || /^https?:\/\/\S+$/.test(text)) {
        return text.split(/[?#]/)[0]
    }
    return ''
}

/** Every string at any depth, such as `$current_url`, an autocaptured `href`, or a request in a replay snapshot.
 * A value with nothing to redact is returned as it is, so a large snapshot is not copied. */
function redactValue(value: unknown, seen: WeakSet<object>): unknown {
    if (typeof value === 'string') {
        return redactMetricVariableUrl(value)
    }
    if (!value || typeof value !== 'object' || seen.has(value)) {
        return value
    }
    seen.add(value)
    if (Array.isArray(value)) {
        let copy: unknown[] | null = null
        value.forEach((item, index) => {
            const redacted = redactValue(item, seen)
            if (redacted !== item) {
                copy ??= [...value]
                copy[index] = redacted
            }
        })
        return copy ?? value
    }
    let copy: Record<string, unknown> | null = null
    for (const [key, item] of Object.entries(value)) {
        const redacted = redactValue(item, seen)
        if (redacted !== item) {
            copy ??= { ...value }
            copy[key] = redacted
        }
    }
    return copy ?? value
}

function redactProperties(properties: Record<string, any> | undefined): Record<string, any> | undefined {
    return properties && (redactValue(properties, new WeakSet()) as Record<string, any>)
}

export const redactMetricVariableUrls: BeforeSendFn = (event) =>
    event && {
        ...event,
        properties: redactProperties(event.properties) ?? event.properties,
        $set: redactProperties(event.$set),
        $set_once: redactProperties(event.$set_once),
    }

function bodyText(body: unknown): string {
    return typeof body === 'string' ? body : JSON.stringify(body)
}

// A custom replay mask replaces the SDK's own body scrubbing, so the mask repeats it. These match posthog-js:
// the words of its payload deny list, and its checks for card numbers and US social security numbers.
const BODY_DENY_LIST = [
    'password',
    'secret',
    'passwd',
    'api_key',
    'apikey',
    'auth',
    'credentials',
    'mysql_pwd',
    'privatekey',
    'private_key',
    'token',
]
const CARD_PATTERN =
    /^(?:(4[0-9]{12}(?:[0-9]{3})?)|(5[1-5][0-9]{14})|(6(?:011|5[0-9]{2})[0-9]{12})|(3[47][0-9]{13})|(3(?:0[0-5]|[68][0-9])[0-9]{11})|((?:2131|1800|35[0-9]{3})[0-9]{11}))$/
const CARD_CANDIDATE = /(^|[^0-9A-Za-z_])([0-9][0-9 -]*[0-9])(?=$|[^0-9A-Za-z_])/g
const CARD_LENGTHS = [16, 15, 14, 13]
const SSN_CANDIDATE = /(^|[^0-9])((?!000|666)[0-9]{3}-?(?!00)[0-9]{2}-?(?!0000)[0-9]{4})(?=$|([^0-9]))/g
const IDENTIFIER_CHARACTER = /[0-9A-Za-z_]/

function passesLuhnCheck(digits: string): boolean {
    let sum = 0
    let double = false
    for (let index = digits.length - 1; index >= 0; index--) {
        let digit = digits.charCodeAt(index) - 48
        if (double) {
            digit *= 2
            if (digit > 9) {
                digit -= 9
            }
        }
        sum += digit
        double = !double
    }
    return sum % 10 === 0
}

function containsCardNumber(text: string): boolean {
    for (const match of text.matchAll(CARD_CANDIDATE)) {
        const candidate = match[2].replace(/[- ]/g, '')
        for (let start = 0; start < candidate.length; start++) {
            for (const length of CARD_LENGTHS) {
                const digits = candidate.slice(start, start + length)
                if (digits.length === length && CARD_PATTERN.test(digits) && passesLuhnCheck(digits)) {
                    return true
                }
            }
        }
    }
    return false
}

function containsSocialSecurityNumber(text: string): boolean {
    for (const match of text.matchAll(SSN_CANDIDATE)) {
        const [, before, , after] = match
        if (!(before && after && IDENTIFIER_CHARACTER.test(before) && IDENTIFIER_CHARACTER.test(after))) {
            return true
        }
    }
    return false
}

/** A body that holds a credential, a card number, a social security number or metric variables is not recorded. */
function scrubBody<T>(body: T, label: 'Request' | 'Response', drop: boolean): T | string | null {
    if (body === null || body === undefined) {
        return body
    }
    const text = bodyText(body)
    if (drop || text.includes(MARKER)) {
        return null
    }
    const denied = BODY_DENY_LIST.find((word) => text.includes(word))
    if (denied) {
        return `[SessionRecording] ${label} body redacted as might contain: ${denied}`
    }
    if (containsCardNumber(text.trim()) || containsSocialSecurityNumber(text.trim())) {
        return `[SessionRecording] ${label} body redacted`
    }
    return body
}

/** For session replay: a recorded request keeps its URL path only when it holds metric variables, and its bodies get
 * the SDK's sensitive-data scrubbing as well as losing anything that holds metric variables. */
export function redactMetricVariableRequest(request: CapturedNetworkRequest): CapturedNetworkRequest {
    const isVariableOptions = !!request.name?.includes(VARIABLE_OPTIONS_PATH)
    return {
        ...request,
        name: request.name ? redactMetricVariableUrl(request.name) : request.name,
        requestBody: scrubBody(request.requestBody, 'Request', isVariableOptions),
        responseBody: scrubBody(request.responseBody, 'Response', isVariableOptions),
    } as CapturedNetworkRequest
}
