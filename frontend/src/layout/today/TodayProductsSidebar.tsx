import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconFolder } from '@posthog/icons'
import { Text } from '@posthog/quill'

import { ReleaseStageBadge } from 'lib/components/ReleaseStageTag/ReleaseStageBadge'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { LibraryCreateButton } from 'scenes/library/LibraryCreateButton'
import { libraryLogic } from 'scenes/library/libraryLogic'
import { libraryListHref, libraryTypeForPath } from 'scenes/library/libraryUtils'
import { libraryRowProductLabels, toolHrefForPath } from 'scenes/tools/toolsUtils'
import { urls } from 'scenes/urls'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { TodayPaneGroupLabel } from './TodayPaneGroupLabel'
import { TodayPaneRow } from './TodayPaneRow'
import { matchesPaneQuery, viewTypesForPaneSearch } from './todayPaneSearch'
import { TodayPaneSearchList } from './TodayPaneSearchList'
import { TodayProductsViewsHint } from './TodayProductsViewsHint'
import { TodayProductRow, libraryRecentKey, recentKeyPath } from './todayRecentProducts'
import { todayRecentProductsLogic } from './todayRecentProductsLogic'
import { TodayProductSection, todayToolsLogic } from './todayToolsLogic'

/** The Products sub-nav: recently viewed tools, every saved object type, then the tools by category. */
export function TodayProductsSidebar(): JSX.Element {
    const { tools, productPages, productSections, recentProducts, search } = useValues(todayToolsLogic)
    const { setSearch } = useActions(todayToolsLogic)
    const { pickProduct } = useActions(todayRecentProductsLogic)
    const { objectTypes } = useValues(libraryLogic)
    const { location } = useValues(router)
    const path = removeProjectIdIfPresent(location.pathname)
    const activeHref = toolHrefForPath(path, tools)
    // Recently viewed also lists Library pages, so its highlight matches against every product page.
    const activeRecentHref = toolHrefForPath(path, productPages)
    const objectPageType = libraryTypeForPath(path)

    const showAllObjects = matchesPaneQuery('All objects', search)
    const libraryTypes = objectTypes.filter((type) =>
        [type.pluralLabel, ...libraryRowProductLabels(type.value)].some((label) => matchesPaneQuery(label, search))
    )
    const showLibrary = showAllObjects || libraryTypes.length > 0
    const searchedViewTypes = viewTypesForPaneSearch(search)
    const recentSection: TodayProductSection | null = recentProducts.length
        ? { key: 'recent', label: 'Recently viewed', rows: recentProducts }
        : null
    const isActive = (sectionKey: string, row: TodayProductRow): boolean =>
        sectionKey === 'recent'
            ? recentKeyPath(row.key) === path || row.key === activeRecentHref
            : !!row.href && row.href === activeHref
    const hasProducts = !!recentSection || showLibrary || productSections.length > 0

    const renderProductSection = (section: TodayProductSection, first: boolean): JSX.Element => (
        <div key={section.key}>
            <TodayPaneGroupLabel first={first}>{section.label}</TodayPaneGroupLabel>
            {section.rows.map((row) => (
                <TodayPaneRow
                    key={row.key}
                    // A product can show in Recently viewed and in its own group, so the group keeps the two rows apart on the keyboard path.
                    value={`${section.key}:${row.key}`}
                    label={row.label}
                    icon={iconForType(row.iconType, row.iconColor)}
                    // Unreleased products sit in their own group, so only alpha and beta get a badge.
                    badge={row.stage && row.stage !== 'internal' ? <ReleaseStageBadge stage={row.stage} /> : null}
                    to={row.href}
                    active={isActive(section.key, row)}
                    dataAttr={section.key === 'recent' ? 'today-tool-recent' : 'today-tool'}
                    onClick={() => pickProduct(row.key)}
                />
            ))}
        </div>
    )

    return (
        <div className="TodayPane group/colorful-product-icons colorful-product-icons-true" data-quill>
            <TodayPaneSearchList
                query={search}
                onQueryChange={setSearch}
                searchLabel="Search products"
                dataAttr="today-products-search"
            >
                {!hasProducts && !searchedViewTypes.length && (
                    <Text size="xs" variant="muted" className="block px-2 py-1">
                        No products match that search.
                    </Text>
                )}
                {recentSection && renderProductSection(recentSection, true)}
                {showLibrary && (
                    <div>
                        <TodayPaneGroupLabel first={!recentSection}>Library</TodayPaneGroupLabel>
                        {showAllObjects && (
                            <TodayPaneRow
                                value="library:all"
                                label="All objects"
                                icon={<IconFolder />}
                                to={urls.library()}
                                active={path === urls.library()}
                                dataAttr="today-library-all"
                            />
                        )}
                        {libraryTypes.map((type) => (
                            <TodayPaneRow
                                key={type.value}
                                value={`library:${type.value}`}
                                label={type.pluralLabel}
                                icon={iconForType(type.value as FileSystemIconType)}
                                to={libraryListHref(type.value) ?? urls.library(type.value)}
                                // A product page can share a scene with a Library list. The product's own row then takes the highlight.
                                active={
                                    path === urls.library(type.value) || (objectPageType === type.value && !activeHref)
                                }
                                action={<LibraryCreateButton objectType={type.value} />}
                                dataAttr="today-library-type"
                                onClick={() => pickProduct(libraryRecentKey(type.value))}
                            />
                        ))}
                    </div>
                )}
                {productSections.map((section, index) =>
                    renderProductSection(section, !recentSection && !showLibrary && index === 0)
                )}
                {searchedViewTypes.length > 0 && <TodayProductsViewsHint viewTypes={searchedViewTypes} />}
            </TodayPaneSearchList>
        </div>
    )
}
