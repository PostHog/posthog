export interface SecretReentryRefusal {
    key: string
    detail: string
}

const INPUTS_ATTR_PREFIX = 'inputs__'

export function parseSecretReentryRefusal(error: unknown): SecretReentryRefusal | null {
    const data = (error as { data?: { code?: unknown; attr?: unknown; detail?: unknown } } | null)?.data
    if (
        data?.code !== 'secret_reentry_required' ||
        typeof data.attr !== 'string' ||
        !data.attr.startsWith(INPUTS_ATTR_PREFIX) ||
        typeof data.detail !== 'string'
    ) {
        return null
    }
    return { key: data.attr.slice(INPUTS_ATTR_PREFIX.length), detail: data.detail }
}
