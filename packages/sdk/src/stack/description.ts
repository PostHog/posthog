import type { RefAttr } from '../define/definition.js'
import type { JsonObject, JsonValue } from '../types.js'

export const DESCRIPTION_VERSION = 1

export interface ResourceSource {
    // Relative to the repository root, with forward slashes.
    file: string
    export?: string
}

// Another definition in the stack that must exist before this one is created.
export interface ResourceDependency {
    kind: string
    key: string
}

export interface ResourceDescription {
    kind: string
    key: string
    body: JsonObject
    source?: ResourceSource
    // Definitions the body names by a string rather than a `$ref`, such as a model whose table a
    // query reads. Sorted, without duplicates, and left out when empty. Not sent to PostHog.
    depends_on?: ResourceDependency[]
}

// What `check` evaluates a stack folder into, and all PostHog receives of it.
export interface StackDescription {
    version: typeof DESCRIPTION_VERSION
    resources: ResourceDescription[]
}

export interface RefValue {
    $ref: { kind: string; key: string; attr?: RefAttr }
}

export type ProblemSeverity = 'error' | 'warning'

export interface StackProblem {
    // Stable, so scripts and agents can branch on it.
    code: string
    severity: ProblemSeverity
    message: string
    kind?: string
    key?: string
    // Where in the body, as `tiles[2].insight` or `query.source.query`.
    path?: string
    // Relative to the repository root.
    file?: string
    line?: number
}

export function isRefValue(value: unknown): value is RefValue {
    if (typeof value !== 'object' || value === null || Array.isArray(value) || !('$ref' in value)) {
        return false
    }
    const target = (value as { $ref: unknown }).$ref
    return (
        typeof target === 'object' &&
        target !== null &&
        typeof (target as { kind?: unknown }).kind === 'string' &&
        typeof (target as { key?: unknown }).key === 'string'
    )
}

export function sortKeys(value: JsonValue): JsonValue {
    if (Array.isArray(value)) {
        return value.map(sortKeys)
    }
    if (value !== null && typeof value === 'object') {
        const sorted: JsonObject = {}
        for (const name of Object.keys(value).sort()) {
            sorted[name] = sortKeys(value[name] as JsonValue)
        }
        return sorted
    }
    return value
}

export function compareResources(a: { kind: string; key: string }, b: { kind: string; key: string }): number {
    if (a.kind !== b.kind) {
        return a.kind < b.kind ? -1 : 1
    }
    return a.key < b.key ? -1 : a.key > b.key ? 1 : 0
}

// Byte-identical for one commit: sorted keys, two-space indent, a final newline.
export function formatDescription(description: StackDescription): string {
    return `${JSON.stringify(sortKeys(description as unknown as JsonValue), null, 2)}\n`
}

export function formatPath(segments: readonly (string | number)[]): string {
    let path = ''
    for (const segment of segments) {
        path += typeof segment === 'number' ? `[${segment}]` : path ? `.${segment}` : segment
    }
    return path
}

// `tiles[3].insight` becomes `tiles[].insight`, the form the kind registry declares positions in.
export function pathPattern(path: string): string {
    return path.replace(/\[\d+\]/g, '[]')
}
