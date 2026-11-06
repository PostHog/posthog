import { ApiConfig } from 'lib/api'
import { userLogic } from 'scenes/userLogic'

export type TaggedResource = 'datasets' | 'experiments' | 'scorers'

export interface ResourceTagFilters {
    tags: string[]
    tag_match: 'any' | 'all'
}

export function cleanTagFilters(values: { tags?: unknown; tag_match?: unknown }): ResourceTagFilters {
    let tags = values.tags
    if (typeof tags === 'string') {
        try {
            tags = JSON.parse(tags)
        } catch {
            tags = []
        }
    }
    return {
        tags: Array.isArray(tags)
            ? [
                  ...new Set(
                      tags
                          .filter((tag): tag is string => typeof tag === 'string')
                          .map((tag) => tag.trim().toLowerCase())
                          .filter(Boolean)
                  ),
              ].slice(0, 20)
            : [],
        tag_match: values.tag_match === 'all' ? 'all' : 'any',
    }
}

function preferenceKey(entity: TaggedResource, teamId: number | string, userId: number | undefined): string {
    // Persisted key: keep the version stable unless the stored filter shape changes.
    return `aio-tag-filters:v1:${userId ?? 'unknown'}:${teamId}:${entity}`
}

export function restoreTagFilters(
    entity: TaggedResource,
    search: Record<string, unknown>,
    teamId: number | string = ApiConfig.getCurrentTeamId(),
    userId: number | undefined = userLogic.findMounted()?.values.user?.id
): ResourceTagFilters {
    if ('tags' in search || 'tag_match' in search) {
        return cleanTagFilters(search)
    }
    try {
        const value: unknown = JSON.parse(localStorage.getItem(preferenceKey(entity, teamId, userId)) || 'null')
        return cleanTagFilters(value && typeof value === 'object' ? value : {})
    } catch {
        return cleanTagFilters({})
    }
}

export function saveTagFilters(
    entity: TaggedResource,
    filters: ResourceTagFilters,
    teamId: number | string = ApiConfig.getCurrentTeamId(),
    userId: number | undefined = userLogic.findMounted()?.values.user?.id
): void {
    try {
        localStorage.setItem(preferenceKey(entity, teamId, userId), JSON.stringify(cleanTagFilters(filters)))
    } catch {
        // Storage may be disabled; URL-backed filters still work.
    }
}
