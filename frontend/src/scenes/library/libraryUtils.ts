import { routes } from 'scenes/scenes'

import { fileSystemTypes, getTreeItemsMetadata, getTreeItemsProducts } from '~/products'
import { FileSystemEntry, FileSystemImport } from '~/queries/schema/schema-general'
import { FileSystemType } from '~/types'

// These file system types are working pages rather than saved objects, so they belong to Tools.
export const TOOL_FILE_SYSTEM_TYPES = new Set(['endpoints', 'task'])
// These file system types are views people open and read, so they belong to Views, next to canvases.
export const VIEW_FILE_SYSTEM_TYPES = new Set(['dashboard', 'notebook'])

// The objects people reach for most come first. Any other type follows in name order.
const LIBRARY_TYPE_ORDER = ['insight', 'feature_flag', 'experiment', 'survey', 'cohort', 'action']

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

/** The file system type of a product page, from its type or, when it has none, its icon. */
export function productObjectType(item: Pick<FileSystemImport, 'type' | 'iconType'>): string {
    return baseObjectType(item.type) || item.iconType || ''
}

/** Whether a file system type shows in Library, rather than in Tools or Views. */
export function isLibraryType(type: string): boolean {
    return !TOOL_FILE_SYSTEM_TYPES.has(type) && !VIEW_FILE_SYSTEM_TYPES.has(type)
}

export function isLibraryEntry(entry: Pick<FileSystemEntry, 'type'>): boolean {
    return isLibraryType(baseObjectType(entry.type))
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

/** The product's own list page for a type, if its manifest registers one. */
export function libraryListHref(type: string): string | null {
    const definition = Object.hasOwn(fileSystemTypes, type)
        ? (fileSystemTypes[type as keyof typeof fileSystemTypes] as FileSystemType)
        : null
    return definition?.listHref?.() ?? null
}

/** Whether a Library type row opens this product's page, so the product needs no row of its own. */
export function libraryRowOpensProduct(item: Pick<FileSystemImport, 'type' | 'iconType' | 'href'>): boolean {
    const type = productObjectType(item)
    return !!item.href && isLibraryType(type) && libraryListHref(type) === item.href
}

const REF_PLACEHOLDER = 'LIBRARY_REF'

function routeSegments(route: string): string[] {
    return route.split(/[?#]/)[0].split('/').filter(Boolean)
}

let parsedRoutes: { scene: string; parts: string[] }[] | null = null
let objectTypeByScene: Map<string, string> | null = null

// The router prefers a fixed segment to a parameter, so `/feature_flags/templates` opens its own scene.
function sceneForPath(path: string): string | null {
    parsedRoutes ??= Object.entries(routes).map(([route, [scene]]) => ({ scene, parts: routeSegments(route) }))
    const segments = routeSegments(path)
    let best: { scene: string; params: number } | null = null
    for (const { scene, parts } of parsedRoutes) {
        const wildcard = parts[parts.length - 1] === '*'
        const fixedLength = wildcard ? parts.length - 1 : parts.length
        if (wildcard ? segments.length <= fixedLength : segments.length !== fixedLength) {
            continue
        }
        if (!parts.slice(0, fixedLength).every((part, index) => part.startsWith(':') || part === segments[index])) {
            continue
        }
        const params = parts.filter((part) => part.startsWith(':') || part === '*').length
        if (!best || params < best.params) {
            best = { scene, params }
        }
    }
    return best?.scene ?? null
}

export function libraryTypeForPath(path: string): string | null {
    if (!objectTypeByScene) {
        const scenes = new Map<string, string>()
        const addPage = (type: string, href: string | undefined): void => {
            const scene = href && isLibraryType(type) ? sceneForPath(href) : null
            if (scene && !scenes.has(scene)) {
                scenes.set(scene, type)
            }
        }
        for (const [type, definition] of Object.entries(fileSystemTypes) as [string, FileSystemType][]) {
            addPage(type, definition.href?.(REF_PLACEHOLDER))
            addPage(type, definition.listHref?.())
        }
        for (const item of [...getTreeItemsProducts(), ...getTreeItemsMetadata()]) {
            const type = productObjectType(item)
            if (Object.hasOwn(fileSystemTypes, type)) {
                addPage(type, item.href)
            }
        }
        objectTypeByScene = scenes
    }
    const scene = sceneForPath(path)
    return (scene && objectTypeByScene.get(scene)) || null
}

/** The last segment of a file system path, with escaped slashes restored. */
export function libraryObjectName(entry: Pick<FileSystemEntry, 'path'>): string {
    const segments = entry.path.split(/(?<!\\)\//)
    return (segments[segments.length - 1] || entry.path).replace(/\\\//g, '/')
}

/** The type's name in lower case, for a label beside an object: "feature flag", but "SQL insight" keeps its acronym. */
export function libraryTypeLabel(type: string | undefined): string | null {
    const baseType = baseObjectType(type)
    const name = Object.hasOwn(fileSystemTypes, baseType)
        ? (fileSystemTypes[baseType as keyof typeof fileSystemTypes] as FileSystemType).name
        : null
    if (!name) {
        return null
    }
    return /^[A-Z]{2}/.test(name) ? name : name.charAt(0).toLowerCase() + name.slice(1)
}

export function sortLibraryTypes(types: LibraryObjectType[]): LibraryObjectType[] {
    const rank = (type: LibraryObjectType): number => {
        const index = LIBRARY_TYPE_ORDER.indexOf(type.value)
        return index === -1 ? LIBRARY_TYPE_ORDER.length : index
    }
    return [...types].sort((first, second) => rank(first) - rank(second) || first.label.localeCompare(second.label))
}
