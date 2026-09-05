import { CyclotronInputType } from '~/cdp/schema/cyclotron'

import { HogFunctionType } from '../types'

/**
 * Per-entry secrets inside a `dictionary` input.
 *
 * A `secret: true` input is encrypted whole. A dictionary input can instead name some of its own
 * entries in `secret_keys`: those entries' values live in `encrypted_inputs` under the same input
 * key, while the names and every other entry stay in the clear. Python's
 * `posthog/cdp/secret_entries.py` owns the split; this is the read side.
 *
 * The Hog VM is deliberately given only the public half. A destination template forwards a headers
 * dictionary straight onto the fetch queue payload, which cyclotron stores as plaintext JSON, so a
 * VM that could see the credentials would write them there. The executor merges them in instead,
 * immediately before each attempt.
 */

export type ResolvedSecretEntries = { ok: true; entries: Record<string, string> } | { ok: false; error: string }

export function secretEntryNames(input: CyclotronInputType | null | undefined): string[] {
    const names = (input as { secret_keys?: unknown } | null | undefined)?.secret_keys
    if (!Array.isArray(names)) {
        return []
    }
    return names.filter((name): name is string => typeof name === 'string' && name.length > 0)
}

/**
 * Builds the VM's view of the inputs: whole-input secrets replace their public placeholder as
 * before, but a per-entry input keeps its public half so the credentials never reach Hog.
 */
export function mergeInputsForVm(
    inputs: HogFunctionType['inputs'],
    encryptedInputs: HogFunctionType['encrypted_inputs']
): HogFunctionType['inputs'] {
    const merged: NonNullable<HogFunctionType['inputs']> = { ...(inputs ?? {}) }

    for (const [key, encrypted] of Object.entries(encryptedInputs ?? {})) {
        if (secretEntryNames(inputs?.[key]).length > 0) {
            continue
        }
        merged[key] = encrypted
    }

    return merged
}

/**
 * The secret entries of one dictionary input, for merging into an outbound request.
 *
 * An input with no secret entries resolves to none, which is the ordinary case for a destination
 * that sends no credentials. A declared entry with nothing stored fails instead: the request would
 * otherwise reach the receiver with that header missing, which reads there as an unauthenticated
 * caller.
 */
export function resolveSecretEntries(
    inputKey: string,
    hogFunction: Pick<HogFunctionType, 'inputs' | 'encrypted_inputs'>
): ResolvedSecretEntries {
    const declared = secretEntryNames(hogFunction.inputs?.[inputKey])
    if (declared.length === 0) {
        return { ok: true, entries: {} }
    }

    const rawStored = hogFunction.encrypted_inputs?.[inputKey]?.value
    // An absent or malformed store is not a special case: every declared entry is then unresolved,
    // and the error below names them, which is what the person fixing it needs.
    const stored: Record<string, unknown> =
        rawStored && typeof rawStored === 'object' && !Array.isArray(rawStored)
            ? (rawStored as Record<string, unknown>)
            : {}

    const entries: Record<string, string> = {}
    const missing: string[] = []

    for (const name of declared) {
        const leaf = stored[name]
        // A dictionary's values are template strings, but a single-expression template ("{42}")
        // evaluates to a typed value, so accept scalars.
        if (typeof leaf === 'number' || typeof leaf === 'boolean') {
            entries[name] = String(leaf)
            continue
        }
        if (typeof leaf !== 'string' || leaf === '') {
            missing.push(name)
            continue
        }
        entries[name] = leaf
    }

    if (missing.length > 0) {
        return {
            ok: false,
            error: `Secret headers failed to resolve: no value stored for ${missing.join(', ')}. Enter them again.`,
        }
    }

    return { ok: true, entries }
}

/**
 * Merges resolved secret entries over the plaintext headers.
 *
 * HTTP header names are case-insensitive, so a plaintext `authorization` and a secret
 * `Authorization` would otherwise both go on the wire and let the plaintext one win at some
 * receivers. A secret header always replaces a plaintext header of the same name, whatever its
 * casing.
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
