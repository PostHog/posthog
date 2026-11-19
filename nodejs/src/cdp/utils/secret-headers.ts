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
        if (typeof headerValue !== 'string') {
            return {
                ok: false,
                error: `Secret headers failed: the value of ${name} in input ${inputKey} is not text. Refusing to send the request without its credential headers.`,
            }
        }
        headers[name] = headerValue
    }

    return { ok: true, headers }
}
