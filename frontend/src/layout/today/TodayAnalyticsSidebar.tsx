import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconBell, IconBox, IconList, IconNotification, IconPerson, IconPinFilled } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { Logomark } from 'lib/brand'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { analyticsListFiltersFromUrl } from 'scenes/analytics/analyticsListLogic'
import { AnalyticsSpaceGlyph } from 'scenes/analytics/AnalyticsSpaceGlyph'
import { analyticsSpacesLogic } from 'scenes/analytics/analyticsSpacesLogic'
import { AnalyticsTypeIcon } from 'scenes/analytics/AnalyticsTypeIcon'
import { ANALYTICS_TYPE_INFO } from 'scenes/analytics/analyticsUtils'
import { urls } from 'scenes/urls'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { TodayAnalyticsSection, todayAnalyticsLogic } from './todayAnalyticsLogic'
import { TodayPaneRow } from './TodayPaneRow'
import { TodayPaneSearchList } from './TodayPaneSearchList'
import { TodayPaneSection } from './TodayPaneSection'

/** The Analytics sub-nav: the ways to browse, pinned collections, recently viewed items, PostHog's own analytics, and what to keep an eye on. */
export function TodayAnalyticsSidebar(): JSX.Element {
    const { collapsedSections, fromPostHog, recentAnalytics } = useValues(todayAnalyticsLogic)
    const { toggleSection } = useActions(todayAnalyticsLogic)
    const { pinnedSpaces, pinning } = useValues(analyticsSpacesLogic)
    const { togglePin } = useActions(analyticsSpacesLogic)
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
                    count={3 + pinnedSpaces.length}
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
                        label="My work"
                        icon={<IconPerson />}
                        to={urls.analyticsMine()}
                        active={path === urls.analyticsMine()}
                        dataAttr="analytics-sidebar-browse"
                    />
                    <TodayPaneRow
                        value="browse:spaces"
                        label="Collections"
                        icon={<IconBox />}
                        to={urls.analyticsSpaces()}
                        active={path === urls.analyticsSpaces()}
                        dataAttr="analytics-sidebar-browse"
                    />
                    {pinnedSpaces.map((space) => (
                        <TodayPaneRow
                            key={space.path}
                            value={`space:${space.path}`}
                            label={space.name}
                            icon={<AnalyticsSpaceGlyph name={space.name} />}
                            to={urls.analyticsList({ folder: space.path })}
                            active={openFolder === space.path}
                            action={
                                <Tooltip>
                                    <TooltipTrigger
                                        render={
                                            <Button
                                                variant="default"
                                                size="icon-sm"
                                                aria-label={`Unpin ${space.name}`}
                                                loading={pinning === space.path}
                                                onClick={() => togglePin(space)}
                                                data-attr="analytics-sidebar-unpin-space"
                                            />
                                        }
                                    >
                                        <IconPinFilled />
                                    </TooltipTrigger>
                                    <TooltipContent>Unpin</TooltipContent>
                                </Tooltip>
                            }
                            dataAttr="analytics-sidebar-starred-space"
                        />
                    ))}
                </TodayPaneSection>
                {recentAnalytics.length > 0 && (
                    <TodayPaneSection
                        label="Recents"
                        open={isOpen('recents')}
                        count={recentAnalytics.length}
                        showCount={false}
                        onToggle={() => toggleSection('recents')}
                        divider
                        dataAttr="analytics-section-recents"
                    >
                        {recentAnalytics.map((item) => (
                            <TodayPaneRow
                                key={`${item.type}:${item.id}`}
                                value={`recent:${item.type}:${item.id}`}
                                label={item.name}
                                icon={
                                    // eslint-disable-next-line react/forbid-dom-props
                                    <span style={{ color: ANALYTICS_TYPE_INFO[item.type].color }}>
                                        <AnalyticsTypeIcon type={item.type} />
                                    </span>
                                }
                                to={item.href}
                                active={path === removeProjectIdIfPresent(item.href)}
                                dataAttr="analytics-sidebar-recent"
                            />
                        ))}
                    </TodayPaneSection>
                )}
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
                        label="Alerts"
                        icon={<IconBell />}
                        to={urls.alerts()}
                        active={path === urls.alerts()}
                        dataAttr="analytics-sidebar-monitor"
                    />
                    <TodayPaneRow
                        value="monitor:subscriptions"
                        label="Subscriptions"
                        icon={<IconNotification />}
                        to={`${urls.subscriptions()}?tab=mine`}
                        active={path === urls.subscriptions()}
                        dataAttr="analytics-sidebar-monitor"
                    />
                </TodayPaneSection>
            </TodayPaneSearchList>
        </div>
    )
}
