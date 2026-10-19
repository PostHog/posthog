import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconFolder } from '@posthog/icons'
import { Text } from '@posthog/quill'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { LibraryCreateButton } from 'scenes/library/LibraryCreateButton'
import { libraryLogic } from 'scenes/library/libraryLogic'
import { libraryListHref, libraryTypeForPath } from 'scenes/library/libraryUtils'
import { libraryRowProduct, libraryRowProductLabels, toolHrefForPath, toolLabel } from 'scenes/tools/toolsUtils'
import { urls } from 'scenes/urls'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType, FileSystemImport } from '~/queries/schema/schema-general'

import { TodayPaneGroupLabel } from './TodayPaneGroupLabel'
import { TodayPaneRow } from './TodayPaneRow'
import { analyticsTypesForPaneSearch, matchesPaneQuery } from './todayPaneSearch'
import { TodayPaneSearchList } from './TodayPaneSearchList'
import { TodayProductRow } from './TodayProductRow'
import { TodayProductsAnalyticsHint } from './TodayProductsAnalyticsHint'
import { todayToolsLogic } from './todayToolsLogic'

interface ToolSection {
    key: string
    label: string
    tools: FileSystemImport[]
}

/**
 * The Products sub-nav, laid out like the Products tab of the current navigation: starred products first,
 * then recently viewed tools, every saved object type, and the tools by category.
 */
export function TodayProductsSidebar(): JSX.Element {
    const { tools, toolGroups, recentTools, starredTools, search } = useValues(todayToolsLogic)
    const { setSearch } = useActions(todayToolsLogic)
    const { objectTypes } = useValues(libraryLogic)
    const { location } = useValues(router)
    const path = removeProjectIdIfPresent(location.pathname)
    const activeHref = toolHrefForPath(path, tools)
    const objectPageType = libraryTypeForPath(path)

    const showAllObjects = matchesPaneQuery('All objects', search)
    const libraryTypes = objectTypes.filter((type) =>
        [type.pluralLabel, ...libraryRowProductLabels(type.value)].some((label) => matchesPaneQuery(label, search))
    )
    const showLibrary = showAllObjects || libraryTypes.length > 0
    const searchedAnalyticsTypes = analyticsTypesForPaneSearch(search)
    const starredSection: ToolSection | null = starredTools.length
        ? { key: 'starred', label: 'Starred', tools: starredTools }
        : null
    const recentSection: ToolSection | null = recentTools.length
        ? { key: 'recent', label: 'Recently viewed', tools: recentTools }
        : null
    const categorySections: ToolSection[] = toolGroups.map((group) => ({
        key: group.category,
        label: group.category,
        tools: group.tools,
    }))
    const hasProducts = !!starredSection || !!recentSection || showLibrary || categorySections.length > 0
    // A tool can show in several groups, so the group keeps the rows apart on the keyboard path.
    const optionValue = (groupKey: string, tool: FileSystemImport): string => `${groupKey}:${tool.href ?? ''}`
    // A starred product can open a Library list, which the tool list does not match.
    const isActive = (href: string): boolean => {
        const hrefPath = href.split(/[?#]/)[0]
        return href === activeHref || (!activeHref && (path === hrefPath || path.startsWith(`${hrefPath}/`)))
    }

    const renderToolSection = (section: ToolSection, first: boolean): JSX.Element => (
        <div key={section.key}>
            <TodayPaneGroupLabel first={first}>{section.label}</TodayPaneGroupLabel>
            {section.tools.map((tool) => {
                const href = tool.href ?? ''
                return (
                    <TodayProductRow
                        key={href}
                        value={optionValue(section.key, tool)}
                        label={toolLabel(tool)}
                        product={tool}
                        to={href}
                        active={!!href && isActive(href)}
                        pinStar={section.key !== 'starred'}
                        dataAttr={
                            section.key === 'starred'
                                ? 'today-tool-starred'
                                : section.key === 'recent'
                                  ? 'today-tool-recent'
                                  : 'today-tool'
                        }
                    />
                )
            })}
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
                {!hasProducts && !searchedAnalyticsTypes.length && (
                    <Text size="xs" variant="muted" className="block px-2 py-1">
                        No products match that search.
                    </Text>
                )}
                {starredSection && renderToolSection(starredSection, true)}
                {recentSection && renderToolSection(recentSection, !starredSection)}
                {showLibrary && (
                    <div>
                        <TodayPaneGroupLabel first={!starredSection && !recentSection}>Library</TodayPaneGroupLabel>
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
                        {libraryTypes.map((type) => {
                            const product = libraryRowProduct(type.value)
                            const icon = iconForType(type.value as FileSystemIconType)
                            const to = libraryListHref(type.value) ?? urls.library(type.value)
                            // A product page can share a scene with a Library list. The product's own row then takes the highlight.
                            const active =
                                path === urls.library(type.value) || (objectPageType === type.value && !activeHref)
                            const createButton = <LibraryCreateButton objectType={type.value} />
                            return product ? (
                                <TodayProductRow
                                    key={type.value}
                                    value={`library:${type.value}`}
                                    label={type.pluralLabel}
                                    product={product}
                                    to={to}
                                    active={active}
                                    icon={icon}
                                    extraAction={createButton}
                                    dataAttr="today-library-type"
                                />
                            ) : (
                                <TodayPaneRow
                                    key={type.value}
                                    value={`library:${type.value}`}
                                    label={type.pluralLabel}
                                    icon={icon}
                                    to={to}
                                    active={active}
                                    action={createButton}
                                    dataAttr="today-library-type"
                                />
                            )
                        })}
                    </div>
                )}
                {categorySections.map((section, index) =>
                    renderToolSection(section, !starredSection && !recentSection && !showLibrary && index === 0)
                )}
                {searchedAnalyticsTypes.length > 0 && <TodayProductsAnalyticsHint analyticsTypes={searchedAnalyticsTypes} />}
            </TodayPaneSearchList>
        </div>
    )
}
