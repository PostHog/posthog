import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconBell, IconBox, IconList, IconNotification, IconPerson } from '@posthog/icons'

import { Logomark } from 'lib/brand'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { analyticsListFiltersFromUrl } from 'scenes/analytics/analyticsListLogic'
import { AnalyticsSpaceGlyph } from 'scenes/analytics/AnalyticsSpaceGlyph'
import { analyticsSpacesLogic } from 'scenes/analytics/analyticsSpacesLogic'
import { urls } from 'scenes/urls'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { TodayAnalyticsSection, todayAnalyticsLogic } from './todayAnalyticsLogic'
import { TodayPaneRow } from './TodayPaneRow'
import { TodayPaneSearchList } from './TodayPaneSearchList'
import { TodayPaneSection } from './TodayPaneSection'

/** The Analyses sub-nav: the three ways to browse, the spaces a person starred, and what to keep an eye on. */
export function TodayAnalyticsSidebar(): JSX.Element {
    const { collapsedSections, fromPostHog } = useValues(todayAnalyticsLogic)
    const { toggleSection } = useActions(todayAnalyticsLogic)
    const { starredSpaces } = useValues(analyticsSpacesLogic)
    const { location, searchParams } = useValues(router)
    const path = removeProjectIdIfPresent(location.pathname)
    const isOpen = (section: TodayAnalyticsSection): boolean => !collapsedSections.includes(section)
    const listFilters =
        path === urls.analyticsList() || path === urls.analyticsMine()
            ? analyticsListFiltersFromUrl(searchParams)
            : null
    const openFolder = path === urls.analyticsList() ? (listFilters?.folder ?? null) : null

    return (
        <div className="TodayPane group/colorful-product-icons colorful-product-icons-true" data-quill>
            {/* The rows are list options that need the pane list around them; this pane has no search, so the field stays hidden. */}
            <TodayPaneSearchList
                query=""
                onQueryChange={() => {}}
                searchLabel="Search analytics"
                dataAttr="analytics-sidebar-search"
                className="[&>div:first-child]:hidden"
            >
                <TodayPaneSection
                    label="Browse"
                    open={isOpen('browse')}
                    count={3 + starredSpaces.length}
                    showCount={false}
                    onToggle={() => toggleSection('browse')}
                    dataAttr="analytics-section-browse"
                >
                    <TodayPaneRow
                        value="browse:all"
                        label="View all"
                        icon={<IconList />}
                        to={urls.analyticsList()}
                        active={path === urls.analyticsList() && openFolder === null}
                        dataAttr="analytics-sidebar-browse"
                    />
                    <TodayPaneRow
                        value="browse:mine"
                        label="My analytics"
                        icon={<IconPerson />}
                        to={urls.analyticsMine()}
                        active={path === urls.analyticsMine()}
                        dataAttr="analytics-sidebar-browse"
                    />
                    <TodayPaneRow
                        value="browse:spaces"
                        label="Spaces"
                        icon={<IconBox />}
                        to={urls.analyticsSpaces()}
                        active={path === urls.analyticsSpaces()}
                        dataAttr="analytics-sidebar-browse"
                    />
                    {starredSpaces.map((space) => (
                        <div key={space.path} className="pl-4">
                            <TodayPaneRow
                                value={`space:${space.path}`}
                                label={space.name}
                                icon={<AnalyticsSpaceGlyph name={space.name} />}
                                to={urls.analyticsList({ folder: space.path })}
                                active={openFolder === space.path}
                                dataAttr="analytics-sidebar-starred-space"
                            />
                        </div>
                    ))}
                </TodayPaneSection>
                <TodayPaneSection
                    label="Monitor"
                    open={isOpen('monitor')}
                    count={2}
                    showCount={false}
                    onToggle={() => toggleSection('monitor')}
                    divider
                    dataAttr="analytics-section-monitor"
                >
                    <TodayPaneRow
                        value="monitor:alerts"
                        label="My alerts"
                        icon={<IconBell />}
                        to={urls.alerts()}
                        active={path === urls.alerts()}
                        dataAttr="analytics-sidebar-monitor"
                    />
                    <TodayPaneRow
                        value="monitor:subscriptions"
                        label="My subscriptions"
                        icon={<IconNotification />}
                        to={`${urls.subscriptions()}?tab=mine`}
                        active={path === urls.subscriptions()}
                        dataAttr="analytics-sidebar-monitor"
                    />
                </TodayPaneSection>
                {fromPostHog.length > 0 && (
                    <TodayPaneSection
                        label="By PostHog"
                        icon={<Logomark className="h-auto w-3.5" />}
                        open={isOpen('by-posthog')}
                        count={fromPostHog.length}
                        showCount={false}
                        onToggle={() => toggleSection('by-posthog')}
                        divider
                        dataAttr="analytics-section-by-posthog"
                    >
                        {fromPostHog.map((product) => {
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
            </TodayPaneSearchList>
        </div>
    )
}
