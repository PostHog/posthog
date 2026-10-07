import { propertyDefinitionsList } from '~/generated/core/api'

type CheckableType = 'event' | 'person'

// The endpoint reads any other type as an event property, which would flag an existing key as missing.
const CHECKABLE_TYPES: ReadonlySet<string> = new Set<CheckableType>(['event', 'person'])

function isCheckableType(type: unknown): type is CheckableType {
    return typeof type === 'string' && CHECKABLE_TYPES.has(type)
}

const MAX_CONCURRENT_CHECKS = 4

interface KeyCheck {
    projectId: number
    key: string
    missing: boolean
}

export interface PropertyKeyRef {
    key: string
    type: CheckableType
}

/** Property keys a filter refers to, with their type, in the order the reader added them. */
export function propertyKeysIn(properties: unknown): PropertyKeyRef[] {
    if (!Array.isArray(properties)) {
        return []
    }
    const seen = new Set<string>()
    const refs: PropertyKeyRef[] = []
    for (const property of properties) {
        const { key, type } = (property && typeof property === 'object' ? property : {}) as Record<string, unknown>
        if (typeof key !== 'string' || !key || !isCheckableType(type)) {
            continue
        }
        if (!seen.has(`${type}:${key}`)) {
            seen.add(`${type}:${key}`)
            refs.push({ key, type })
        }
    }
    return refs
}

/**
 * A filter travels by key name, so a key one project never recorded silently empties that tile.
 * Checked on filter apply only, because a check on open costs a request per project and key.
 */
export async function findMissingPropertyKeys(
    projectIds: number[],
    refs: PropertyKeyRef[]
): Promise<Record<number, string[]>> {
    if (projectIds.length === 0 || refs.length === 0) {
        return {}
    }

    const pairs = projectIds.flatMap((projectId) => refs.map((ref) => ({ projectId, ...ref })))
    const check = async ({ projectId, key, type }: { projectId: number } & PropertyKeyRef): Promise<KeyCheck> => {
        try {
            const response = await propertyDefinitionsList(String(projectId), { search: key, type, limit: 100 })
            const found = response.results.some((definition) => definition.name === key)
            return { projectId, key, missing: !found }
        } catch {
            // A project the reader cannot reach answers 403. That is not a missing key, and
            // claiming it is would put a warning on a tile whose data is fine.
            return { projectId, key, missing: false }
        }
    }

    const results: KeyCheck[] = []
    for (let start = 0; start < pairs.length; start += MAX_CONCURRENT_CHECKS) {
        results.push(...(await Promise.all(pairs.slice(start, start + MAX_CONCURRENT_CHECKS).map(check))))
    }

    const missing: Record<number, string[]> = {}
    for (const result of results) {
        if (result.missing) {
            missing[result.projectId] = [...(missing[result.projectId] ?? []), result.key]
        }
    }
    return missing
}
