import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { isFileSystemImportShown } from 'lib/utils/fileSystemImportFlags'

import { getNavProductPages } from '~/layout/panel-layout/navbar/tabs/navProductItems'
import { splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemIconType, FileSystemImport } from '~/queries/schema/schema-general'

import type { TodayRecent, TodayRecentTypeCopy } from './todayRecents'

export interface TodayPaneProductSpec {
    href: string
    /** A path whose pages belong to the product even though no row links to them, such as AI observability's traces. */
    section?: string
    /** The row's entry when the product list has none for `href`, such as a tab of another product. */
    item?: FileSystemImport
    /** The icon of the page header the row opens, when it differs from the product list's icon. */
    iconType?: FileSystemIconType
    /** The row's key when it differs from its icon type. */
    key?: string
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
    return specs.flatMap(({ href, section, item: ownItem, iconType, key }) => {
        const listed = ownItem ?? pages.find((page) => page.href === href)
        if (!listed) {
            return []
        }
        const item = iconType ? { ...listed, iconType } : listed
        const matchPaths = [href.split(/[?#]/)[0], ...(section ? [section] : [])]
        const label = item.displayLabel || splitPath(item.path).at(-1) || item.path
        return [{ key: key ?? item.iconType ?? href, label, href, item, matchPaths }]
    })
}

/** Whether the Products pane shows this product for these flags, so a pane never lists a page the Products pane hides. */
export function isPaneProductShown(product: TodayPaneProduct, featureFlags: FeatureFlagsSet): boolean {
    return isFileSystemImportShown(product.item, featureFlags)
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

export type TodayProductPaneKey = 'monitor' | 'automate' | 'data'

export interface TodayPaneGroup {
    // pinned: the persisted id of a collapsed section, the `section` of `<pane> section toggled`, and part of the
    // section's `data-attr`.
    id: string
    // pinned: the `data-attr` prefix of the group's rows.
    rowDataAttr: string
    specs: () => TodayPaneProductSpec[]
}

export interface TodayPaneSection extends TodayPaneGroup {
    label: string
}

export interface TodayProductPaneConfig {
    pane: TodayProductPaneKey
    label: string
    /** The products above Pinned and Recents, with no header. */
    lead: TodayPaneGroup
    sections: TodayPaneSection[]
    recentTypes: readonly string[]
    recentTypeInfo: Record<string, TodayRecentTypeCopy & { iconType: FileSystemIconType }>
    /** Records viewed before this pane existed, newest first, to fill Recents on a first visit. */
    loadRecentHistory?: () => Promise<TodayRecent[]>
}

export interface TodayPaneProducts {
    lead: TodayPaneProduct[]
    sections: { section: TodayPaneSection; products: TodayPaneProduct[] }[]
}

export function paneProducts(config: TodayProductPaneConfig): TodayPaneProducts {
    const pages = getNavProductPages()
    return {
        lead: paneProductsFor(pages, config.lead.specs()),
        sections: config.sections.map((section) => ({ section, products: paneProductsFor(pages, section.specs()) })),
    }
}

export function filterPaneProducts(
    products: TodayPaneProducts,
    keep: (product: TodayPaneProduct) => boolean
): TodayPaneProducts {
    return {
        lead: products.lead.filter(keep),
        sections: products.sections.map(({ section, products }) => ({ section, products: products.filter(keep) })),
    }
}

/** Matches against every product of the pane, shown or not, so a page keeps its pane while a flag hides its row. */
export function paneConfigProductForPath(config: TodayProductPaneConfig, path: string): TodayPaneProduct | undefined {
    const { lead, sections } = paneProducts(config)
    return paneProductForPath([...lead, ...sections.flatMap(({ products }) => products)], path)
}
