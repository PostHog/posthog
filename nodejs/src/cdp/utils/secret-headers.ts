import { HogFunctionType } from '../types'
import { resolveHogFunctionInputValue } from './hog-function-inputs'

export type ResolvedSecretHeaders = { ok: true; headers: Record<string, string> } | { ok: false; error: string }

export function resolveSecretHeaders(
    inputKey: string,
    hogFunction: Pick<HogFunctionType, 'inputs' | 'encrypted_inputs'>
): ResolvedSecretHeaders {
    const value = resolveHogFunctionInputValue(hogFunction, inputKey)

    if (typeof value !== 'object' || value === null || Array.isArray(value)) {
        return {
            ok: false,
            error: `Secret headers failed: input ${inputKey} not found on hog function or not a dictionary. Refusing to send the request without its credential headers.`,
        }
    }

    const headers: Record<string, string> = {}
    for (const [name, headerValue] of Object.entries(value)) {
        if (typeof headerValue === 'string') {
            headers[name] = headerValue
        }
    }

    return { ok: true, headers }
}

// Some receivers read the first of two same-name headers, so a plaintext header a secret header also sets is dropped.
export function mergeSecretHeaders(
    headers: Record<string, string>,
    secretHeaders: Record<string, string>
): Record<string, string> {
    const secretNames = new Set(Object.keys(secretHeaders).map((name) => name.toLowerCase()))

    const merged: Record<string, string> = {}
    for (const [name, value] of Object.entries(headers)) {
        if (!secretNames.has(name.toLowerCase())) {
            merged[name] = value
        }
    }

    return { ...merged, ...secretHeaders }
}
