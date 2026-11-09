export interface InputRefusal {
    key: string
    detail: string
}

const INPUTS_ATTR_PREFIX = 'inputs__'

function parseInputRefusal(error: unknown, code: string): InputRefusal | null {
    const data = (error as { data?: { code?: unknown; attr?: unknown; detail?: unknown } } | null)?.data
    if (
        data?.code !== code ||
        typeof data.attr !== 'string' ||
        !data.attr.startsWith(INPUTS_ATTR_PREFIX) ||
        typeof data.detail !== 'string'
    ) {
        return null
    }
    return { key: data.attr.slice(INPUTS_ATTR_PREFIX.length), detail: data.detail }
}

export function parseSecretReentryRefusal(error: unknown): InputRefusal | null {
    return parseInputRefusal(error, 'secret_reentry_required')
}

// Entering a value again does not fix a connection refusal, so the form marks the input instead of asking.
export function parseConnectionRefusal(error: unknown): InputRefusal | null {
    return parseInputRefusal(error, 'integration_origin_refused')
}
