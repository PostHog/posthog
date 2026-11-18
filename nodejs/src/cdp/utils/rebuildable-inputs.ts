import { createHash } from 'node:crypto'

import type { HogFunctionMappingType, HogFunctionType } from '../types'
import { HogConfigurationError } from './hog-error-classification'

/**
 * Persisted job state holds this in place of the built inputs. The executor builds the inputs again from the
 * function config, so the job queue never stores a secret that a template or a secret input put into them.
 */
export type RebuildableInputsSource = {
    /** The mapping that created the invocation. Absent for a function without mappings. */
    mapping?: { index: number; fingerprint: string }
}

// The compiled filter fields change when the compiler changes, not when the user edits the mapping.
const COMPILED_FILTER_KEYS = new Set(['bytecode', 'transpiled', 'bytecode_error', 'bytecode_contract'])

const stableJson = (value: unknown): string => {
    if (Array.isArray(value)) {
        return `[${value.map(stableJson).join(',')}]`
    }
    if (value && typeof value === 'object') {
        const entries = Object.entries(value)
            .filter(([, item]) => item !== undefined)
            .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
        return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${stableJson(item)}`).join(',')}}`
    }
    return JSON.stringify(value ?? null)
}

/**
 * Identifies a mapping by its name and its trigger filters. A mapping has no id, and its position changes when
 * the user adds, removes or moves a mapping. Its input values are not part of it: the rebuild uses the current
 * values, as it does for the function's own inputs.
 */
export const mappingFingerprint = (mapping: HogFunctionMappingType): string => {
    const filters = Object.fromEntries(
        Object.entries(mapping.filters ?? {}).filter(([key]) => !COMPILED_FILTER_KEYS.has(key))
    )
    return createHash('sha256')
        .update(stableJson({ name: mapping.name ?? null, filters }))
        .digest('hex')
        .slice(0, 32)
}

export const rebuildableInputsSource = (
    hogFunction: HogFunctionType,
    mapping?: HogFunctionMappingType
): RebuildableInputsSource => {
    if (!mapping) {
        return {}
    }
    return {
        mapping: { index: hogFunction.mappings?.indexOf(mapping) ?? -1, fingerprint: mappingFingerprint(mapping) },
    }
}

const MAPPING_CHANGED_MESSAGE =
    'The mapping that created this invocation was changed or removed after the invocation was queued, so its inputs could not be built again.'

/**
 * Finds the mapping whose inputs the rebuild adds. The mapping at the stored index wins when it still matches.
 * Otherwise exactly one mapping must match, because two equal mappings cannot be told apart.
 */
export const findRebuildMapping = (
    hogFunction: HogFunctionType,
    source: RebuildableInputsSource
): HogFunctionMappingType | undefined => {
    const mappings = hogFunction.mappings ?? []
    if (!source.mapping) {
        if (mappings.length > 0) {
            throw new HogConfigurationError(MAPPING_CHANGED_MESSAGE)
        }
        return undefined
    }

    const { index, fingerprint } = source.mapping
    const atIndex = mappings[index]
    if (atIndex && mappingFingerprint(atIndex) === fingerprint) {
        return atIndex
    }
    const matches = mappings.filter((mapping) => mappingFingerprint(mapping) === fingerprint)
    if (matches.length !== 1) {
        throw new HogConfigurationError(MAPPING_CHANGED_MESSAGE)
    }
    return matches[0]
}
