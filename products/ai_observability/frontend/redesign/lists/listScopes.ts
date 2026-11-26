import type { AiObservabilityTracesListParams } from '../../generated/api.schemas'
import { rawSearchParam } from '../trace/rawSearchParam'

// pinned: each kind is also its URL param, which links from other tabs and saved links carry
export const LIST_SCOPE_KINDS = ['person', 'error', 'tool'] as const

export type ListScopeKind = (typeof LIST_SCOPE_KINDS)[number]

export interface ListScope {
    kind: ListScopeKind
    value: string
}

export function scopeFromUrl(search: string, kinds: readonly ListScopeKind[]): ListScope | null {
    for (const kind of kinds) {
        const value = rawSearchParam(search, kind)
        if (value) {
            return { kind, value }
        }
    }
    return null
}

export function scopeRequestParams(
    scope: ListScope | null
): Pick<AiObservabilityTracesListParams, 'person_id' | 'error' | 'tool'> {
    switch (scope?.kind) {
        case 'person':
            return { person_id: scope.value }
        case 'error':
            return { error: scope.value }
        case 'tool':
            return { tool: scope.value }
        default:
            return {}
    }
}

const PERSON_LABEL_LENGTH = 8

export function scopeLabel(scope: ListScope): string {
    // A person UUID is a UUIDv7, whose leading characters are its creation time, so people created close together
    // share them. The trailing characters are random.
    return scope.kind === 'person' ? scope.value.slice(-PERSON_LABEL_LENGTH) : scope.value
}
