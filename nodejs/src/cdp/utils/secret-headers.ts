import { HogFunctionType } from '../types'
import { resolveHogFunctionInputValue } from './hog-function-inputs'

export type ResolvedSecretHeaders = { ok: true; headers: Record<string, string> } | { ok: false; error: string }

export function resolveSecretHeaders(
    secretHeadersInput: string,
    hogFunction: Pick<HogFunctionType, 'inputs' | 'encrypted_inputs'>
): ResolvedSecretHeaders {
    const value = resolveHogFunctionInputValue(hogFunction, secretHeadersInput)

    if (!value || typeof value !== 'object' || Array.isArray(value)) {
        return {
            ok: false,
            error: `Secret headers failed to resolve: input ${secretHeadersInput} was not found on this destination, or is not a dictionary. Refusing to send the request without its secret headers.`,
        }
    }

    const headers: Record<string, string> = {}

    for (const [key, leaf] of Object.entries(value)) {
        if (!key) {
            continue
        }
        // A dictionary input's values are template strings, but a single-expression
        // template ("{42}") evaluates to a typed value, so accept scalars.
        if (typeof leaf === 'number' || typeof leaf === 'boolean') {
            headers[key] = String(leaf)
            continue
        }
        if (typeof leaf !== 'string') {
            return {
                ok: false,
                error: `Secret headers failed to resolve: header ${key} is not a string. Refusing to send the request without its secret headers.`,
            }
        }
        // These carry credentials, so an empty value means the value never made it
        // into storage. Say so here rather than letting the receiver answer 401.
        if (leaf === '') {
            return {
                ok: false,
                error: `Secret headers failed to resolve: header ${key} is empty. Enter its value again.`,
            }
        }
        headers[key] = leaf
    }

    if (Object.keys(headers).length === 0) {
        return {
            ok: false,
            error: `Secret headers failed to resolve: input ${secretHeadersInput} is empty. Refusing to send the request without its secret headers.`,
        }
    }

    return { ok: true, headers }
}

/**
 * Merges resolved secret headers over the plaintext ones.
 *
 * HTTP header names are case-insensitive, so a plaintext `authorization` and a
 * secret `Authorization` would otherwise both go on the wire and let the
 * plaintext one win at some receivers. A secret header always replaces any
 * plaintext header of the same name, whatever its casing.
 */
export function mergeSecretHeaders(
    headers: Record<string, string>,
    secretHeaders: Record<string, string>
): Record<string, string> {
    const overridden = new Set(Object.keys(secretHeaders).map((key) => key.toLowerCase()))
    const merged: Record<string, string> = {}

    for (const [key, value] of Object.entries(headers)) {
        if (!overridden.has(key.toLowerCase())) {
            merged[key] = value
        }
    }

    return { ...merged, ...secretHeaders }
}
