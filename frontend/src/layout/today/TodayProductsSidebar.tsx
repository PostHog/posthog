import { useActions, useValues } from 'kea'

import { Text } from '@posthog/quill'

import { NavProductIcon } from '~/layout/panel-layout/navbar/tabs/NavProductIcon'
import { productsItemName } from '~/layout/panel-layout/navbar/tabs/productsCatalog'
import { FileSystemImport } from '~/queries/schema/schema-general'

import { TodayPaneGroupLabel } from './TodayPaneGroupLabel'
import { TodayPaneRow } from './TodayPaneRow'
import { analyticsTypesForPaneSearch } from './todayPaneSearch'
import { TodayPaneSearchList } from './TodayPaneSearchList'
import { TodayPaneSection } from './TodayPaneSection'
import { TodayProductRow } from './TodayProductRow'
import { TodayProductsAnalyticsHint } from './TodayProductsAnalyticsHint'
import { todayProductsLogic } from './todayProductsLogic'

export function TodayProductsSidebar(): JSX.Element {
    const {
        pinnedProducts,
        productGroups,
        productCount,
        starredProducts,
        starredHrefs,
        starredOpen,
        allProductsOpen,
        activeHref,
        search,
    } = useValues(todayProductsLogic)
    const { setSearch, setStarredOpen, setAllProductsOpen } = useActions(todayProductsLogic)
    const searching = !!search.trim()
    const searchedAnalyticsTypes = analyticsTypesForPaneSearch(search)
    const hasProducts = pinnedProducts.length > 0 || starredProducts.length > 0 || productCount > 0

    // A product can show in Starred and in its category, so the group keeps the rows apart on the keyboard path.
    const renderProduct = (item: FileSystemImport, group: string): JSX.Element => (
        <TodayProductRow
            key={item.href}
            value={`${group}:${item.href}`}
            label={productsItemName(item)}
            product={item}
            to={item.href ?? ''}
            active={item.href === activeHref}
            starred={starredHrefs.has(item.href ?? '')}
            inStarredGroup={group === 'starred'}
        />
    )

    return (
        <div className="TodayPane group/colorful-product-icons colorful-product-icons-true" data-quill>
            <TodayPaneSearchList
                query={search}
                onQueryChange={setSearch}
                searchLabel="Search products"
                dataAttr="today-products-search"
            >
                {!hasProducts &&
                    (searchedAnalyticsTypes.length > 0 ? (
                        <TodayProductsAnalyticsHint analyticsTypes={searchedAnalyticsTypes} />
                    ) : (
                        <Text size="xs" variant="muted" className="block px-2 py-1">
                            No products match that search.
                        </Text>
                    ))}
                {pinnedProducts.length > 0 && (
                    <div className="flex flex-col gap-px pb-2">
                        {pinnedProducts.map((item) => (
                            <TodayPaneRow
                                key={item.href}
                                value={`pinned:${item.href}`}
                                label={productsItemName(item)}
                                icon={<NavProductIcon item={item} />}
                                to={item.href ?? ''}
                                active={item.href === activeHref}
                                dataAttr="today-tool-pinned"
                            />
                        ))}
                    </div>
                )}
                {starredProducts.length > 0 && (
                    <TodayPaneSection
                        label="Starred"
                        open={starredOpen || searching}
                        count={starredProducts.length}
                        onToggle={() => setStarredOpen(!starredOpen)}
                        dataAttr="today-section-starred"
                    >
                        {starredProducts.map((item) => renderProduct(item, 'starred'))}
                    </TodayPaneSection>
                )}
                {productCount > 0 && (
                    <TodayPaneSection
                        label="All products"
                        open={allProductsOpen || searching}
                        count={productCount}
                        onToggle={() => setAllProductsOpen(!allProductsOpen)}
                        dataAttr="today-section-all-products"
                    >
                        {productGroups.map((group, index) => (
                            <div key={group.label}>
                                <TodayPaneGroupLabel first={index === 0}>{group.label}</TodayPaneGroupLabel>
                                {group.items.map((item) => renderProduct(item, group.label))}
                            </div>
                        ))}
                    </TodayPaneSection>
                )}
            </TodayPaneSearchList>
        </div>
    )
}
