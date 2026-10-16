import { ReleaseStage, releaseStage } from 'lib/components/ReleaseStageTag/releaseStage'
import { LibraryObjectType, libraryListHref, libraryTypeForPath } from 'scenes/library/libraryUtils'
import { toolCategory, toolHrefForPath, toolLabel } from 'scenes/tools/toolsUtils'
import { urls } from 'scenes/urls'

import { FileSystemIconType, FileSystemImport } from '~/queries/schema/schema-general'

/**
 * A recently viewed product is either a product page, keyed by its href, or a Library type, keyed as `library:<type>`.
 * Library keys exist because some Library pages have no product page (replay playlists) or share one (Worksheets opens Business intelligence).
 */
const LIBRARY_KEY_PREFIX = 'library:'

/** One row in the Products pane, from a product page or a Library type. */
export interface TodayProductRow {
    key: string
    label: string
    href: string
    iconType: FileSystemIconType
    iconColor?: FileSystemImport['iconColor']
    stage: ReleaseStage | null
    /** The text a pane search matches against. */
    searchText: string
}

export function libraryRecentKey(type: string): string {
    return `${LIBRARY_KEY_PREFIX}${type}`
}

function libraryTypeOfKey(key: string): string | null {
    return key.startsWith(LIBRARY_KEY_PREFIX) ? key.slice(LIBRARY_KEY_PREFIX.length) : null
}

function libraryHref(type: string): string {
    return libraryListHref(type) ?? urls.library(type)
}

/** The page a key opens. Two keys for one page, such as Worksheets and Business intelligence, share it. */
export function recentKeyPath(key: string): string {
    const type = libraryTypeOfKey(key)
    return (type ? libraryHref(type) : key).split(/[?#]/)[0]
}

/** A row the person picked. It replaces any older key for the same page. */
export function pickRecentKey(keys: string[], key: string, limit: number): string[] {
    const path = recentKeyPath(key)
    return [key, ...keys.filter((existing) => recentKeyPath(existing) !== path)].slice(0, limit)
}

/** A page visit. A key for the same page moves to the front and keeps the row the person last picked. */
export function touchRecentKey(keys: string[], key: string, limit: number): string[] {
    const path = recentKeyPath(key)
    return pickRecentKey(keys, keys.find((existing) => recentKeyPath(existing) === path) ?? key, limit)
}

/** The key for a visited page: its product page first, else the Library type that owns it. */
export function recentKeyForPath(path: string, productPages: FileSystemImport[]): string | null {
    const href = toolHrefForPath(path, productPages)
    if (href) {
        return href
    }
    const type = libraryTypeForPath(path)
    return type ? libraryRecentKey(type) : null
}

export function productPageRow(page: FileSystemImport): TodayProductRow {
    const label = toolLabel(page)
    return {
        key: page.href ?? '',
        label,
        href: page.href ?? '',
        iconType: (page.iconType ?? page.type) as FileSystemIconType,
        iconColor: page.iconColor,
        stage: releaseStage(page),
        searchText: `${label} ${toolCategory(page)}`,
    }
}

function libraryTypeRow(objectType: LibraryObjectType): TodayProductRow {
    return {
        key: libraryRecentKey(objectType.value),
        label: objectType.pluralLabel,
        href: libraryHref(objectType.value),
        iconType: objectType.value as FileSystemIconType,
        stage: null,
        searchText: objectType.pluralLabel,
    }
}

/** The row for a key, or null when the page is gone or this person cannot open it. */
export function recentProductRow(
    key: string,
    productPages: FileSystemImport[],
    objectTypes: LibraryObjectType[]
): TodayProductRow | null {
    const type = libraryTypeOfKey(key)
    const page = type ? null : productPages.find((candidate) => candidate.href === key)
    const objectType = type ? objectTypes.find((candidate) => candidate.value === type) : null
    return page ? productPageRow(page) : objectType ? libraryTypeRow(objectType) : null
}
