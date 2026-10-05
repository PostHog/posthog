import { baseObjectType, libraryObjectName } from 'scenes/library/libraryUtils'

import type { TodayObjectPreview } from '~/layout/today/todayPreviewCards'
import { fileSystemTypes } from '~/products'
import { FileSystemEntry } from '~/queries/schema/schema-general'

/** Recently viewed objects for the home, without tasks, which are agent sessions rather than things people look at. */
export function recentObjectsForHome(recents: FileSystemEntry[], limit: number): FileSystemEntry[] {
    return recents.filter((entry) => !!entry.href && baseObjectType(entry.type) !== 'task').slice(0, limit)
}

/** The type's name for use mid-sentence: "feature flag", but "SQL insight" keeps its acronym. */
export function typeNameInProse(type: string | undefined | null): string | null {
    const name = (fileSystemTypes as Record<string, { name: string }>)[baseObjectType(type ?? undefined)]?.name
    if (!name) {
        return null
    }
    return /^[A-Z]{2}/.test(name) ? name : name.charAt(0).toLowerCase() + name.slice(1)
}

export function objectPreview(entry: FileSystemEntry): TodayObjectPreview {
    const segments = entry.path.split(/(?<!\\)\//)
    const folder = segments.slice(0, -1).join('/').replace(/\\\//g, '/')
    const createdAt = entry.meta?.created_at ?? entry.created_at
    return {
        kind: 'object',
        name: libraryObjectName(entry),
        type: entry.type ?? null,
        typeName: typeNameInProse(entry.type),
        folder: folder || null,
        lastViewedAt: entry.last_viewed_at ?? null,
        createdAt: typeof createdAt === 'string' ? createdAt : null,
    }
}
