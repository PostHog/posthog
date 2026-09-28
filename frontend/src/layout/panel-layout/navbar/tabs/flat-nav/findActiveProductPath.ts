import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { FileSystemImport } from '~/queries/schema/schema-general'

function hrefPathname(product: FileSystemImport): string | undefined {
    return product.href?.split(/[?#]/)[0] || undefined
}

/** Whether `currentPath` (already stripped of its project id) is on a product's page or one of its subpages. */
export function isProductActive(product: FileSystemImport, currentPath: string): boolean {
    const href = hrefPathname(product)
    if (!href) {
        return false
    }
    if (currentPath === href) {
        return true
    }
    if (href === urls.projectRoot()) {
        return currentPath === urls.projectHomepage()
    }
    // Session replay links to /replay/home, but recordings and playlists live on sibling /replay/ paths
    if (product.path === 'Session replay' && currentPath.startsWith('/replay/')) {
        return true
    }
    return currentPath.startsWith(`${href}/`)
}

export function findActiveProductPath(pathname: string, products: FileSystemImport[]): string | null {
    const currentPath = removeProjectIdIfPresent(pathname)
    let active: FileSystemImport | null = null
    for (const product of products) {
        if (!isProductActive(product, currentPath)) {
            continue
        }
        // The longest href wins, so /workflows/broadcasts is Broadcasts and not Workflows
        if (!active || (hrefPathname(product)?.length ?? 0) > (hrefPathname(active)?.length ?? 0)) {
            active = product
        }
    }
    return active?.path ?? null
}
