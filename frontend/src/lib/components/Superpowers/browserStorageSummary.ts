import { isKeaPersistedKey, storageEntryBytes } from 'lib/utils/keaStorage'

export interface BrowserStorageGroup {
    pattern: string
    keyCount: number
    bytes: number
    lastUsed: number | null
    persistedByKea: boolean
}

export interface BrowserStorageSummary {
    totalBytes: number
    keyCount: number
    groups: BrowserStorageGroup[]
}

export function storageKeyPattern(key: string): string {
    return key
        .replace(/^\d+_/, '*_')
        .replace(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi, '*')
        .replace(/toolu_[A-Za-z0-9]+/g, '*')
        .replace(/\d+/g, '*')
}

export function summarizeBrowserStorage(
    entries: [key: string, value: string][],
    lastUsed: Record<string, number>
): BrowserStorageSummary {
    const groups = new Map<string, BrowserStorageGroup>()
    let totalBytes = 0
    for (const [key, value] of entries) {
        const bytes = storageEntryBytes(key, value)
        totalBytes += bytes
        const pattern = storageKeyPattern(key)
        const group = groups.get(pattern) ?? {
            pattern,
            keyCount: 0,
            bytes: 0,
            lastUsed: null,
            persistedByKea: isKeaPersistedKey(key),
        }
        group.keyCount += 1
        group.bytes += bytes
        const used = lastUsed[key]
        if (used !== undefined && (group.lastUsed === null || used > group.lastUsed)) {
            group.lastUsed = used
        }
        groups.set(pattern, group)
    }
    return {
        totalBytes,
        keyCount: entries.length,
        groups: [...groups.values()].sort((a, b) => b.bytes - a.bytes),
    }
}
