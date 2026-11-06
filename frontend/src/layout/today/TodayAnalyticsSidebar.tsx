import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { Fragment, useMemo } from 'react'

import { IconBell, IconBox, IconList, IconNotification, IconPerson } from '@posthog/icons'

import { Logomark } from 'lib/brand'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { analyticsListFiltersFromUrl } from 'scenes/analytics/analyticsListLogic'
import { AnalyticsPinButton } from 'scenes/analytics/AnalyticsPinButton'
import { analyticsPinnedLogic } from 'scenes/analytics/analyticsPinnedLogic'
import { AnalyticsSpaceGlyph } from 'scenes/analytics/AnalyticsSpaceGlyph'
import { AnalyticsTypeIcon } from 'scenes/analytics/AnalyticsTypeIcon'
import { ANALYTICS_TYPE_INFO, AnalyticsType } from 'scenes/analytics/analyticsUtils'
import { urls } from 'scenes/urls'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { todayAnalyticsLogic } from './todayAnalyticsLogic'
import { TodayPaneRow } from './TodayPaneRow'
import { TodayPaneSearchList } from './TodayPaneSearchList'
import { TodayPaneSection } from './TodayPaneSection'
import { TodayExplainerPreview, productPreview } from './todayPreviewCards'
import { TodayPreviewTrigger } from './TodayPreviewTrigger'

// Module constants, so the shared hover card gets the same payload on every render.
const EXPLAINERS = {
    all: {
        kind: 'explainer',
        label: 'View all',
        icon: <IconList />,
        description:
            'Browse every canvas, dashboard, notebook, and insight your project shares. Filter by type, creator, or collection.',
        example: 'Find the retention dashboard a teammate made last month.',
    },
    mine: {
        kind: 'explainer',
        label: 'My work',
        icon: <IconPerson />,
        description: 'See everything you created, including work you have not shared with your project yet.',
        example: 'Pick up a draft insight you started yesterday.',
    },
    collections: {
        kind: 'explainer',
        label: 'Collections',
        icon: <IconBox />,
        description:
            'Keep related analytics together where your team can find it. Pin a collection to show it in this sidebar.',
        example: 'Keep all the growth team’s dashboards and insights in one collection.',
    },
    alerts: {
        kind: 'explainer',
        label: 'Alerts',
        icon: <IconBell />,
        description: 'Watch the metrics in your insights and get a notification when a value crosses a threshold.',
        example: 'Get an email when daily signups drop below 100.',
        docsHref: 'https://posthog.com/docs/alerts',
    },
    subscriptions: {
        kind: 'explainer',
        label: 'Subscriptions',
        icon: <IconNotification />,
        description:
            'Get insights and dashboards delivered on a schedule by email or Slack. Manage the subscriptions you have set up.',
        example: 'Send the weekly activation dashboard to your team every Monday.',
    },
} satisfies Record<string, TodayExplainerPreview>

function AnalyticsItemIcon({ type }: { type: AnalyticsType }): JSX.Element {
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <span style={{ color: ANALYTICS_TYPE_INFO[type].color }}>
            <AnalyticsTypeIcon type={type} />
        </span>
    )
}

interface ExplainerRow {
    value: string
    explainer: (typeof EXPLAINERS)[keyof typeof EXPLAINERS]
    to: string
    dataAttr: string
}

/** A fixed row whose hover card explains it. Its label and icon come from the explainer. */
function ExplainerPaneRow({ row, active }: { row: ExplainerRow; active: boolean }): JSX.Element {
    return (
        <TodayPreviewTrigger payload={row.explainer}>
            <TodayPaneRow
                value={row.value}
                label={row.explainer.label}
                icon={row.explainer.icon}
                to={row.to}
                active={active}
                dataAttr={row.dataAttr}
            />
        </TodayPreviewTrigger>
    )
}

/** The Analytics sub-nav: the ways to browse, pinned items and collections, recently viewed items, PostHog's own analytics, and what to keep an eye on. */
export function TodayAnalyticsSidebar(): JSX.Element {
    const { fromPostHog, recentAnalytics, searchQuery, matchesSearch, isSectionOpen } = useValues(todayAnalyticsLogic)
    const { toggleSection, setSearchQuery } = useActions(todayAnalyticsLogic)
    const { pinnedAnalytics } = useValues(analyticsPinnedLogic)
    const { location, searchParams } = useValues(router)
    const path = removeProjectIdIfPresent(location.pathname)
    const listFilters =
        path === urls.analyticsList() || path === urls.analyticsMine()
            ? analyticsListFiltersFromUrl(searchParams)
            : null
    const openFolder = path === urls.analyticsList() ? (listFilters?.folder ?? null) : null
    const fromPostHogPreviews = useMemo(
        () => new Map(fromPostHog.map((product) => [product.key, productPreview(product.label, product.item)])),
        [fromPostHog]
    )

    const browseRows: (ExplainerRow & { active: boolean })[] = [
        {
            value: 'browse:all',
            explainer: EXPLAINERS.all,
            to: urls.analyticsList(),
            active: path === urls.analyticsList() && openFolder === null,
            dataAttr: 'analytics-sidebar-browse',
        },
        {
            value: 'browse:mine',
            explainer: EXPLAINERS.mine,
            to: urls.analyticsMine(),
            active: path === urls.analyticsMine(),
            dataAttr: 'analytics-sidebar-browse',
        },
        {
            value: 'browse:spaces',
            explainer: EXPLAINERS.collections,
            to: urls.analyticsSpaces(),
            active: path === urls.analyticsSpaces(),
            dataAttr: 'analytics-sidebar-browse',
        },
    ].filter((row) => matchesSearch(row.explainer.label))
    const monitorRows: (ExplainerRow & { active: boolean })[] = [
        {
            value: 'monitor:alerts',
            explainer: EXPLAINERS.alerts,
            to: urls.alerts(),
            active: path === urls.alerts(),
            dataAttr: 'analytics-sidebar-monitor',
        },
        {
            value: 'monitor:subscriptions',
            explainer: EXPLAINERS.subscriptions,
            to: `${urls.subscriptions()}?tab=mine`,
            active: path === urls.subscriptions(),
            dataAttr: 'analytics-sidebar-monitor',
        },
    ].filter((row) => matchesSearch(row.explainer.label))
    const pinnedRows = pinnedAnalytics.filter((pinned) =>
        matchesSearch(pinned.kind === 'collection' ? pinned.name : pinned.item.name)
    )
    const recentRows = recentAnalytics.filter((item) => matchesSearch(item.name))
    const fromPostHogRows = fromPostHog.filter((product) => matchesSearch(product.label))
    const noMatches =
        browseRows.length + monitorRows.length + pinnedRows.length + recentRows.length + fromPostHogRows.length === 0

    return (
        <div className="TodayPane group/colorful-product-icons colorful-product-icons-true" data-quill>
            <TodayPaneSearchList
                query={searchQuery}
                onQueryChange={setSearchQuery}
                searchLabel="Search analytics"
                dataAttr="analytics-sidebar-search"
            >
                {browseRows.length > 0 && (
                    <div className="flex flex-col gap-px pb-2">
                        {browseRows.map((row) => (
                            <ExplainerPaneRow key={row.value} row={row} active={row.active} />
                        ))}
                    </div>
                )}
                {noMatches && (
                    <div className="px-2 py-1 text-sm text-muted-foreground">
                        Nothing in Analytics matches your search.
                    </div>
                )}
                {pinnedRows.length > 0 && (
                    <TodayPaneSection
                        label="Pinned"
                        open={isSectionOpen('pinned')}
                        count={pinnedRows.length}
                        showCount={false}
                        onToggle={() => toggleSection('pinned')}
                        dataAttr="analytics-section-pinned"
                    >
                        {pinnedRows.map((pinned) =>
                            pinned.kind === 'collection' ? (
                                <TodayPaneRow
                                    key={pinned.key}
                                    value={`pinned:${pinned.key}`}
                                    label={pinned.name}
                                    icon={<AnalyticsSpaceGlyph name={pinned.name} />}
                                    to={urls.analyticsList({ folder: pinned.path })}
                                    active={openFolder === pinned.path}
                                    action={
                                        <AnalyticsPinButton
                                            target={{ type: 'folder', ref: pinned.path, name: pinned.name }}
                                            // pinned: tracking API, do not rename.
                                            dataAttr="analytics-sidebar-unpin-space"
                                        />
                                    }
                                    // pinned: tracking API, do not rename.
                                    dataAttr="analytics-sidebar-starred-space"
                                />
                            ) : (
                                <TodayPaneRow
                                    key={pinned.key}
                                    value={`pinned:${pinned.key}`}
                                    label={pinned.item.name}
                                    icon={<AnalyticsItemIcon type={pinned.item.type} />}
                                    to={pinned.item.href}
                                    active={path === removeProjectIdIfPresent(pinned.item.href)}
                                    action={
                                        <AnalyticsPinButton
                                            target={{
                                                type: pinned.item.type,
                                                ref: pinned.item.id,
                                                name: pinned.item.name,
                                                href: pinned.item.href,
                                            }}
                                            dataAttr="analytics-sidebar-unpin"
                                        />
                                    }
                                    dataAttr="analytics-sidebar-pinned"
                                />
                            )
                        )}
                    </TodayPaneSection>
                )}
                {recentRows.length > 0 && (
                    <TodayPaneSection
                        label="Recents"
                        open={isSectionOpen('recents')}
                        count={recentRows.length}
                        showCount={false}
                        onToggle={() => toggleSection('recents')}
                        divider
                        dataAttr="analytics-section-recents"
                    >
                        {recentRows.map((item) => (
                            <TodayPaneRow
                                key={`${item.type}:${item.id}`}
                                value={`recent:${item.type}:${item.id}`}
                                label={item.name}
                                icon={<AnalyticsItemIcon type={item.type} />}
                                to={item.href}
                                active={path === removeProjectIdIfPresent(item.href)}
                                action={
                                    <AnalyticsPinButton
                                        target={{ type: item.type, ref: item.id, name: item.name, href: item.href }}
                                        dataAttr="analytics-sidebar-recent-pin"
                                    />
                                }
                                dataAttr="analytics-sidebar-recent"
                            />
                        ))}
                    </TodayPaneSection>
                )}
                {fromPostHogRows.length > 0 && (
                    <TodayPaneSection
                        label="By PostHog"
                        icon={<Logomark className="h-auto w-3.5" />}
                        open={isSectionOpen('by-posthog')}
                        count={fromPostHogRows.length}
                        showCount={false}
                        onToggle={() => toggleSection('by-posthog')}
                        divider
                        dataAttr="analytics-section-by-posthog"
                    >
                        {fromPostHogRows.map((product) => {
                            const productPath = product.href.split(/[?#]/)[0]
                            const row = (
                                <TodayPaneRow
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
                            const preview = fromPostHogPreviews.get(product.key)
                            return preview?.description ? (
                                <TodayPreviewTrigger key={product.key} payload={preview}>
                                    {row}
                                </TodayPreviewTrigger>
                            ) : (
                                <Fragment key={product.key}>{row}</Fragment>
                            )
                        })}
                    </TodayPaneSection>
                )}
                {monitorRows.length > 0 && (
                    <TodayPaneSection
                        label="Monitor"
                        open={isSectionOpen('monitor')}
                        count={monitorRows.length}
                        showCount={false}
                        onToggle={() => toggleSection('monitor')}
                        divider
                        dataAttr="analytics-section-monitor"
                    >
                        {monitorRows.map((row) => (
                            <ExplainerPaneRow key={row.value} row={row} active={row.active} />
                        ))}
                    </TodayPaneSection>
                )}
            </TodayPaneSearchList>
        </div>
    )
}
