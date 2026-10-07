import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconFolder } from '@posthog/icons'
import { Text } from '@posthog/quill'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { LibraryCreateButton } from 'scenes/library/LibraryCreateButton'
import { libraryLogic } from 'scenes/library/libraryLogic'
import { libraryListHref, libraryTypeForPath } from 'scenes/library/libraryUtils'
import { toolHrefForPath, toolLabel } from 'scenes/tools/toolsUtils'
import { urls } from 'scenes/urls'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType, FileSystemImport } from '~/queries/schema/schema-general'

import { TodayPaneGroupLabel } from './TodayPaneGroupLabel'
import { TodayPaneRow } from './TodayPaneRow'
import { matchesPaneQuery } from './todayPaneSearch'
import { TodayPaneSearchList } from './TodayPaneSearchList'
import { todayToolsLogic } from './todayToolsLogic'

/** The Products sub-nav: recently viewed tools, every saved object type, then the tools by category. */
export function TodayProductsSidebar(): JSX.Element {
    const { tools, toolGroups, recentTools, search } = useValues(todayToolsLogic)
    const { setSearch } = useActions(todayToolsLogic)
    const { objectTypes } = useValues(libraryLogic)
    const { location } = useValues(router)
    const path = removeProjectIdIfPresent(location.pathname)
    const activeHref = toolHrefForPath(path, tools)
    const objectPageType = libraryTypeForPath(path)

    const showAllObjects = matchesPaneQuery('All objects', search)
    const libraryTypes = objectTypes.filter(
        (type) => type.value !== 'session_recording_playlist' && matchesPaneQuery(type.pluralLabel, search)
    )
    const showLibrary = showAllObjects || libraryTypes.length > 0
    const recentSection = recentTools.length ? { key: 'recent', label: 'Recently viewed', tools: recentTools } : null
    const categorySections = toolGroups.map((group) => ({
        key: group.category,
        label: group.category,
        tools: group.tools,
    }))
    // A tool can show in Recently viewed and in its own group, so the group keeps the two rows apart on the keyboard path.
    const optionValue = (groupKey: string, tool: FileSystemImport): string => `${groupKey}:${tool.href ?? ''}`

    const renderToolSection = (section: (typeof categorySections)[number], first: boolean): JSX.Element => (
        <div key={section.key}>
            <TodayPaneGroupLabel first={first}>{section.label}</TodayPaneGroupLabel>
            {section.tools.map((tool) => {
                const href = tool.href ?? ''
                return (
                    <TodayPaneRow
                        key={href}
                        value={optionValue(section.key, tool)}
                        label={toolLabel(tool)}
                        icon={iconForType((tool.iconType ?? tool.type) as FileSystemIconType, tool.iconColor)}
                        to={href}
                        active={!!href && href === activeHref}
                        dataAttr={section.key === 'recent' ? 'today-tool-recent' : 'today-tool'}
                    />
                )
            })}
        </div>
    )

    return (
        <div className="TodayPane" data-quill>
            <TodayPaneSearchList
                query={search}
                onQueryChange={setSearch}
                searchLabel="Search products"
                dataAttr="today-products-search"
            >
                {!recentSection && !showLibrary && !categorySections.length ? (
                    <Text size="xs" variant="muted" className="block px-2 py-1">
                        No products match that search.
                    </Text>
                ) : (
                    <>
                        {recentSection && renderToolSection(recentSection, true)}
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
                                        active={path === urls.library(type.value) || objectPageType === type.value}
                                        action={<LibraryCreateButton objectType={type.value} />}
                                        dataAttr="today-library-type"
                                    />
                                ))}
                            </div>
                        )}
                        {categorySections.map((section, index) =>
                            renderToolSection(section, !recentSection && !showLibrary && index === 0)
                        )}
                    </>
                )}
            </TodayPaneSearchList>
        </div>
    )
}
