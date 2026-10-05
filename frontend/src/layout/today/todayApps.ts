import { baseObjectType, libraryTypeForPath } from 'scenes/library/libraryUtils'
import { toolHrefForPath } from 'scenes/tools/toolsUtils'

import { FileSystemImport } from '~/queries/schema/schema-general'

/** The app a page belongs to: the longest matching href, else the app that owns the page's object type. */
export function appHrefForPath(path: string, apps: FileSystemImport[]): string | null {
    const href = toolHrefForPath(path, apps)
    if (href) {
        return href
    }
    const objectType = libraryTypeForPath(path)
    return (objectType && apps.find((app) => baseObjectType(app.type) === objectType)?.href) || null
}
