import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { IconFolderPlus, IconPlus, IconTrends } from '@posthog/icons'
import { Button, Spinner, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { Logomark } from 'lib/brand'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { analyticsListFiltersFromUrl } from 'scenes/analytics/analyticsListLogic'
import { AnalyticsTypeIcon } from 'scenes/analytics/AnalyticsTypeIcon'
import {
    ANALYTICS_TYPES,
    ANALYTICS_TYPE_INFO,
    AnalyticsType,
    AnalyticsTypeFilter,
} from 'scenes/analytics/analyticsUtils'
import { newAnalyticsLogic } from 'scenes/analytics/newAnalyticsLogic'
import { NewAnalyticsMenu } from 'scenes/analytics/NewAnalyticsMenu'
import { urls } from 'scenes/urls'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { TodayAnalyticsFolderTree } from './TodayAnalyticsFolderTree'
import { ANALYTICS_SEARCH_LIMIT, TodayAnalyticsSection, todayAnalyticsLogic } from './todayAnalyticsLogic'
import { TodayAnalyticsNewFolderDialog } from './TodayAnalyticsNewFolderDialog'
import { TodayPaneGroupLabel } from './TodayPaneGroupLabel'
import { TodayPaneRow } from './TodayPaneRow'
import { matchesPaneQuery } from './todayPaneSearch'
import { TodayPaneSearchList } from './TodayPaneSearchList'
import { TodayPaneSection } from './TodayPaneSection'
import { shortTimeAgo } from './todayWorkItems'

const BROWSE_ROWS: { type: AnalyticsTypeFilter; label: string }[] = [
    { type: 'all', label: 'View all' },
    ...ANALYTICS_TYPES.map((info) => ({ type: info.type, label: info.pluralLabel })),
]

function IconAction({
    label,
    icon,
    onClick,
    dataAttr,
}: {
    label: string
    icon: JSX.Element
    onClick?: () => void
    dataAttr: string
}): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger
                delay={0}
                render={
                    <Button
                        variant="default"
                        size="icon-xs"
                        aria-label={label}
                        onClick={onClick}
                        data-attr={dataAttr}
                    />
                }
            >
                {icon}
            </TooltipTrigger>
            <TooltipContent side="right">{label}</TooltipContent>
        </Tooltip>
    )
}

/** The Analytics sub-nav: what PostHog ships, every type with a "+", and the project's folders. */
export function TodayAnalyticsSidebar(): JSX.Element {
    const { fromPostHog, collapsedSections, query, search, searchResults, searchFeed, allAnalytics, buildingIds } =
        useValues(todayAnalyticsLogic)
    const { toggleSection, setNewFolderDialogOpen, setQuery } = useActions(todayAnalyticsLogic)
    const { pickNewAnalyticsType } = useActions(newAnalyticsLogic)
    const { folders } = useValues(projectTreeDataLogic)
    const { loadFolder } = useActions(projectTreeDataLogic)
    useMountedLogic(projectTreeDataLogic)
    const { location, searchParams } = useValues(router)
    const path = removeProjectIdIfPresent(location.pathname)
    const listFilters = path === urls.analyticsList() ? analyticsListFiltersFromUrl(searchParams) : null

    const searching = query.trim() !== ''
    const isOpen = (section: TodayAnalyticsSection): boolean => searching || !collapsedSections.includes(section)
    const foldersOpen = isOpen('folders')

    useEffect(() => {
        if (foldersOpen && !folders['']) {
            loadFolder('')
        }
    }, [foldersOpen, folders, loadFolder])

    const byPostHogRows = fromPostHog.filter((product) => matchesPaneQuery(product.label, query))
    const browseRows = BROWSE_ROWS.filter((row) => matchesPaneQuery(row.label, query))
    const showFolders = !searching || matchesPaneQuery('Folders', query)
    const nothingMatches = searching && !byPostHogRows.length && !browseRows.length && !showFolders

    const searchState =
        !searchFeed.initialized && !allAnalytics.initialized ? 'loading' : searchFeed.loadFailed ? 'error' : 'ready'

    return (
        <div className="TodayPane" data-quill>
            <TodayPaneSearchList
                query={query}
                onQueryChange={setQuery}
                searchLabel="Search analytics"
                dataAttr="analytics-sidebar-search"
            >
                {searching && (
                    <div>
                        <TodayPaneGroupLabel first>Results</TodayPaneGroupLabel>
                        {searchState === 'loading' ? (
                            <div className="TodayPane__state" aria-busy>
                                <Spinner />
                            </div>
                        ) : searchState === 'error' && !searchResults.length ? (
                            <div className="TodayPane__state">Your analytics didn’t load.</div>
                        ) : !searchResults.length ? (
                            <div className="TodayPane__state">
                                {search.trim() === query.trim() ? 'Nothing matches.' : 'Searching…'}
                            </div>
                        ) : (
                            searchResults
                                .slice(0, ANALYTICS_SEARCH_LIMIT)
                                .map((item) => (
                                    <TodayPaneRow
                                        key={`${item.type}-${item.id}`}
                                        value={`result:${item.type}-${item.id}`}
                                        label={item.name}
                                        icon={
                                            buildingIds.includes(item.id) ? (
                                                <Spinner />
                                            ) : (
                                                <AnalyticsTypeIcon type={item.type} />
                                            )
                                        }
                                        meta={buildingIds.includes(item.id) ? 'Building' : shortTimeAgo(item.timestamp)}
                                        to={item.href}
                                        active={path === removeProjectIdIfPresent(item.href)}
                                        dataAttr="analytics-sidebar-result"
                                    />
                                ))
                        )}
                    </div>
                )}
                {nothingMatches && (
                    <Text size="xs" variant="muted" className="block px-2 py-1">
                        Nothing in Analytics matches that search.
                    </Text>
                )}
                {byPostHogRows.length > 0 && (
                    <TodayPaneSection
                        label="By PostHog"
                        icon={<Logomark className="h-auto w-3.5" />}
                        open={isOpen('by-posthog')}
                        count={byPostHogRows.length}
                        showCount={false}
                        onToggle={() => toggleSection('by-posthog')}
                        dataAttr="analytics-section-by-posthog"
                    >
                        {byPostHogRows.map((product) => {
                            const productPath = product.href.split(/[?#]/)[0]
                            return (
                                <TodayPaneRow
                                    key={product.key}
                                    value={`by-posthog:${product.key}`}
                                    label={product.label}
                                    icon={iconForType(
                                        (product.item.iconType ?? product.item.type) as FileSystemIconType,
                                        product.item.iconColor
                                    )}
                                    to={product.href}
                                    active={path === productPath || path.startsWith(`${productPath}/`)}
                                    dataAttr="analytics-sidebar-by-posthog"
                                />
                            )
                        })}
                    </TodayPaneSection>
                )}
                {browseRows.length > 0 && (
                    <TodayPaneSection
                        label="Browse"
                        open={isOpen('browse')}
                        count={browseRows.length}
                        showCount={false}
                        onToggle={() => toggleSection('browse')}
                        divider
                        dataAttr="analytics-section-browse"
                    >
                        {browseRows.map((row) => {
                            const analyticsType: AnalyticsType | null = row.type === 'all' ? null : row.type
                            return (
                                <TodayPaneRow
                                    key={row.type}
                                    value={`browse:${row.type}`}
                                    label={row.label}
                                    icon={analyticsType ? <AnalyticsTypeIcon type={analyticsType} /> : <IconTrends />}
                                    to={urls.analyticsList(analyticsType ? { type: analyticsType } : {})}
                                    active={
                                        !!listFilters &&
                                        listFilters.folder === null &&
                                        !listFilters.createdBy &&
                                        listFilters.type === row.type
                                    }
                                    action={
                                        !analyticsType ? (
                                            <NewAnalyticsMenu
                                                source="sidebar"
                                                trigger={
                                                    <Button
                                                        variant="default"
                                                        size="icon-xs"
                                                        aria-label="New"
                                                        data-attr="analytics-sidebar-new-all"
                                                    />
                                                }
                                            >
                                                <IconPlus />
                                            </NewAnalyticsMenu>
                                        ) : (
                                            <IconAction
                                                label={`New ${ANALYTICS_TYPE_INFO[analyticsType].label.toLowerCase()}`}
                                                icon={<IconPlus />}
                                                onClick={() => pickNewAnalyticsType(analyticsType, 'sidebar')}
                                                dataAttr={`analytics-sidebar-new-${analyticsType}`}
                                            />
                                        )
                                    }
                                    dataAttr="analytics-sidebar-browse"
                                />
                            )
                        })}
                    </TodayPaneSection>
                )}
                {showFolders && (
                    <TodayPaneSection
                        label="Folders"
                        open={foldersOpen}
                        count={0}
                        showCount={false}
                        onToggle={() => toggleSection('folders')}
                        divider
                        dataAttr="analytics-section-folders"
                        actions={
                            <IconAction
                                label="New folder"
                                icon={<IconFolderPlus />}
                                onClick={() => setNewFolderDialogOpen(true)}
                                dataAttr="analytics-sidebar-new-folder"
                            />
                        }
                    >
                        <TodayAnalyticsFolderTree dataAttr="analytics-sidebar-folders" />
                    </TodayPaneSection>
                )}
            </TodayPaneSearchList>
            <TodayAnalyticsNewFolderDialog />
        </div>
    )
}
