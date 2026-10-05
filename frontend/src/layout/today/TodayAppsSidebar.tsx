import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconFolder } from '@posthog/icons'
import { Text } from '@posthog/quill'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { LibraryCreateButton } from 'scenes/library/LibraryCreateButton'
import { libraryLogic } from 'scenes/library/libraryLogic'
import { baseObjectType } from 'scenes/library/libraryUtils'
import { urls } from 'scenes/urls'

import { productsItemName } from '~/layout/panel-layout/navbar/tabs/productsCatalog'
import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType, FileSystemImport } from '~/queries/schema/schema-general'

import { appHrefForPath } from './todayApps'
import { todayAppsLogic } from './todayAppsLogic'
import { TodayPaneGroupLabel } from './TodayPaneGroupLabel'
import { TodayPaneRow } from './TodayPaneRow'
import { matchesPaneQuery } from './todayPaneSearch'
import { TodayPaneSearchList } from './TodayPaneSearchList'

export function TodayAppsSidebar(): JSX.Element {
    const { apps, pinnedApps, appGroups, recentApps, search } = useValues(todayAppsLogic)
    const { setSearch } = useActions(todayAppsLogic)
    const { createItemsByType } = useValues(libraryLogic)
    const { location } = useValues(router)
    const path = removeProjectIdIfPresent(location.pathname)
    const activeHref = appHrefForPath(path, apps)
    const showAllObjects = matchesPaneQuery('All objects', search)
    const groups = [
        ...(recentApps.length ? [{ key: 'recent', label: 'Recently viewed', items: recentApps }] : []),
        ...appGroups.map((group) => ({ key: group.label, label: group.label, items: group.items })),
    ]
    // An app can show in Recently viewed and in its own group, so the group keeps the two rows apart on the keyboard path.
    const optionValue = (groupKey: string, app: FileSystemImport): string => `${groupKey}:${app.href ?? ''}`

    const renderRow = (groupKey: string, app: FileSystemImport): JSX.Element => {
        const href = app.href ?? ''
        const objectType = baseObjectType(app.type)
        return (
            <TodayPaneRow
                key={href}
                value={optionValue(groupKey, app)}
                label={productsItemName(app)}
                icon={iconForType((app.iconType ?? app.type) as FileSystemIconType, app.iconColor)}
                to={href}
                active={!!href && href === activeHref}
                action={
                    createItemsByType[objectType]?.length ? <LibraryCreateButton objectType={objectType} /> : undefined
                }
                dataAttr={groupKey === 'recent' ? 'today-app-recent' : 'today-app'}
            />
        )
    }

    return (
        <div className="TodayPane" data-quill>
            <TodayPaneSearchList
                query={search}
                onQueryChange={setSearch}
                searchLabel="Search apps"
                dataAttr="today-apps-search"
            >
                {!showAllObjects && !pinnedApps.length && !groups.length ? (
                    <Text size="xs" variant="muted" className="block px-2 py-1">
                        No apps match that search.
                    </Text>
                ) : (
                    <>
                        {(showAllObjects || pinnedApps.length > 0) && (
                            <div>
                                {showAllObjects && (
                                    <TodayPaneRow
                                        value="all-objects"
                                        label="All objects"
                                        icon={<IconFolder />}
                                        to={urls.library()}
                                        active={path === urls.library()}
                                        dataAttr="today-library-all"
                                    />
                                )}
                                {pinnedApps.map((app) => renderRow('pinned', app))}
                            </div>
                        )}
                        {groups.map((group, index) => (
                            <div key={group.key}>
                                <TodayPaneGroupLabel first={index === 0 && !showAllObjects && !pinnedApps.length}>
                                    {group.label}
                                </TodayPaneGroupLabel>
                                {group.items.map((app) => renderRow(group.key, app))}
                            </div>
                        ))}
                    </>
                )}
            </TodayPaneSearchList>
        </div>
    )
}
