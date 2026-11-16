import { LATEST_VERSIONS } from './latest-versions'
import { NodeKind } from './schema-general'

/**
 * **Needs to be used on all hardcoded queries.**
 *
 * Recursively adds the latest version for the respective kind to each node. This
 * is necessary so that schema migrations don't run on hardcoded queries that
 * are already the latest version. */
export function setLatestVersionsOnQuery<T = any>(node: T, options?: { recursion?: boolean }): T {
    const recursion = options?.recursion ?? true

    if (node === null || typeof node !== 'object') {
        return node
    }

    if (recursion === true && Array.isArray(node)) {
        return (node as unknown as any[]).map((value) => setLatestVersionsOnQuery(value)) as unknown as T
    }

    const cloned: Record<string, any> = { ...(node as any) }

    if (
        'kind' in cloned &&
        Object.values(NodeKind).includes(cloned.kind) &&
        LATEST_VERSIONS[cloned.kind as NodeKind] > 1
    ) {
        const latest = LATEST_VERSIONS[cloned.kind as NodeKind]
        cloned.version = latest || 1
    }

    if (recursion === true) {
        for (const [key, value] of Object.entries(cloned)) {
            if (value !== null && typeof value === 'object') {
                cloned[key] = setLatestVersionsOnQuery(value)
            }
        }
    }

    return cloned as T
}

/** Checks whether a given query node satisfies all latest versions of the query schema. */
export function checkLatestVersionsOnQuery(node: any): boolean {
    if (node === null || typeof node !== 'object') {
        return true
    }

    if (Array.isArray(node)) {
        return node.every((value) => checkLatestVersionsOnQuery(value))
    }

    if ('kind' in node && Object.values(NodeKind).includes(node.kind)) {
        const latest = LATEST_VERSIONS[node.kind as NodeKind]
        if (node.version !== latest) {
            return false
        }
    }

    for (const value of Object.values(node)) {
        if (!checkLatestVersionsOnQuery(value)) {
            return false
        }
    }

    return true
}
