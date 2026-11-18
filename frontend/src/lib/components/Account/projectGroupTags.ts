import { slugify } from 'lib/utils/strings'

export const PROJECT_GROUP_TAG_PREFIX = 'project-group:'

export function isProjectGroupTag(tag: string): boolean {
    return tag.startsWith(PROJECT_GROUP_TAG_PREFIX)
}

export function projectGroupFromTags(tags: string[] | undefined): string | null {
    return tags?.find(isProjectGroupTag)?.slice(PROJECT_GROUP_TAG_PREFIX.length) ?? null
}

export function uniqueProjectGroupNames(groups: (string | null | undefined)[]): string[] {
    return [...new Set(groups.filter((group): group is string => !!group))].sort()
}

export function projectGroupTagFromName(name: string): string | null {
    const slug = slugify(name)
        .replace(/_/g, '-')
        .replace(/-+/g, '-')
        .replace(/^-|-$/g, '')
        .slice(0, 241)
        .replace(/-+$/g, '')
    return slug ? `${PROJECT_GROUP_TAG_PREFIX}${slug}` : null
}
