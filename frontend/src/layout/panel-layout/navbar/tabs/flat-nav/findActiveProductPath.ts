import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { FileSystemImport } from '~/queries/schema/schema-general'

/** Path of the product whose page is open, or null when the page belongs to no product. */
export function findActiveProductPath(pathname: string, products: FileSystemImport[]): string | null {
    const currentPath = removeProjectIdIfPresent(pathname)
    let activePath: string | null = null
    let activeHrefLength = 0
    for (const product of products) {
        const href = product.href?.split(/[?#]/)[0]
        if (!href) {
            continue
        }
        const matches = currentPath === href || (href !== urls.projectRoot() && currentPath.startsWith(`${href}/`))
        // The longest href wins, so /workflows/broadcasts is Broadcasts and not Workflows
        if (matches && href.length > activeHrefLength) {
            activePath = product.path
            activeHrefLength = href.length
        }
    }
    return activePath
}
