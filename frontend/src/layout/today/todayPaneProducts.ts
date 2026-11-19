import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { isFileSystemImportShown } from 'lib/utils/fileSystemImportFlags'

import { splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemImport } from '~/queries/schema/schema-general'

export interface TodayPaneProductSpec {
    href: string
    /** A path whose pages belong to the product even though no row links to them, such as AI observability's traces. */
    section?: string
}

export interface TodayPaneProduct {
    // pinned: part of the row's `data-attr`, so it keeps the product's sidebar `iconType`.
    key: string
    label: string
    href: string
    item: FileSystemImport
    matchPaths: string[]
}

export function paneProductsFor(pages: FileSystemImport[], specs: TodayPaneProductSpec[]): TodayPaneProduct[] {
    return specs.flatMap(({ href, section }) => {
        const item = pages.find((page) => page.href === href)
        if (!item) {
            return []
        }
        const matchPaths = [href.split(/[?#]/)[0], ...(section ? [section] : [])]
        const label = item.displayLabel || splitPath(item.path).at(-1) || item.path
        return [{ key: item.iconType ?? href, label, href, item, matchPaths }]
    })
}

/** The products the Products pane shows for these flags, so a pane never lists a page the Products pane hides. */
export function shownPaneProducts(products: TodayPaneProduct[], featureFlags: FeatureFlagsSet): TodayPaneProduct[] {
    return products.filter((product) => isFileSystemImportShown(product.item, featureFlags))
}

/** The product that owns this page. The longest matching path wins, so a nested product beats its parent. */
export function paneProductForPath(products: TodayPaneProduct[], path: string): TodayPaneProduct | undefined {
    let match: { product: TodayPaneProduct; matchPath: string } | undefined
    for (const product of products) {
        for (const matchPath of product.matchPaths) {
            const matches = path === matchPath || path.startsWith(`${matchPath}/`)
            if (matches && (!match || matchPath.length > match.matchPath.length)) {
                match = { product, matchPath }
            }
        }
    }
    return match?.product
}
