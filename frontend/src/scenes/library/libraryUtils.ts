import { fileSystemTypes } from '~/products'
import { FileSystemEntry } from '~/queries/schema/schema-general'

// These file system types are working pages rather than saved objects, so they belong to Tools.
export const TOOL_FILE_SYSTEM_TYPES = new Set(['endpoints', 'live_debugger', 'notebook', 'task'])

// The objects people reach for most come first. Any other type follows in name order.
const LIBRARY_TYPE_ORDER = ['insight', 'dashboard', 'feature_flag', 'experiment', 'survey', 'cohort', 'action']

export interface LibraryObjectType {
    value: string
    /** Singular, for "New feature flag". */
    label: string
    /** Plural, for the sub-nav. */
    pluralLabel: string
}

export function baseObjectType(type: string | undefined): string {
    return type?.split('/')[0] ?? ''
}

export function isToolEntry(entry: Pick<FileSystemEntry, 'type'>): boolean {
    return TOOL_FILE_SYSTEM_TYPES.has(baseObjectType(entry.type))
}

/** The page a saved object opens, from the entry itself or from its type's registered URL. */
export function libraryObjectHref(entry: Pick<FileSystemEntry, 'href' | 'type' | 'ref'>): string | null {
    if (entry.href) {
        return entry.href
    }
    const baseType = baseObjectType(entry.type)
    const definition = Object.hasOwn(fileSystemTypes, baseType)
        ? fileSystemTypes[baseType as keyof typeof fileSystemTypes]
        : null
    return entry.ref && definition ? definition.href(entry.ref) : null
}

/** The last segment of a file system path, with escaped slashes restored. */
export function libraryObjectName(entry: Pick<FileSystemEntry, 'path'>): string {
    const segments = entry.path.split(/(?<!\\)\//)
    return (segments[segments.length - 1] || entry.path).replace(/\\\//g, '/')
}

export function sortLibraryTypes(types: LibraryObjectType[]): LibraryObjectType[] {
    const rank = (type: LibraryObjectType): number => {
        const index = LIBRARY_TYPE_ORDER.indexOf(type.value)
        return index === -1 ? LIBRARY_TYPE_ORDER.length : index
    }
    return [...types].sort((first, second) => rank(first) - rank(second) || first.label.localeCompare(second.label))
}
