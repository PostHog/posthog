import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { Fragment, Suspense, useMemo } from 'react'

import { Button, SkeletonText } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { analyticsListFiltersFromUrl } from 'scenes/analytics/analyticsListLogic'
import { AnalyticsPinButton } from 'scenes/analytics/AnalyticsPinButton'
import { analyticsPinnedLogic } from 'scenes/analytics/analyticsPinnedLogic'
import { AnalyticsSpaceGlyph } from 'scenes/analytics/AnalyticsSpaceGlyph'
import { AnalyticsTypeIcon } from 'scenes/analytics/AnalyticsTypeIcon'
import { ANALYTICS_TYPE_INFO, AnalyticsType } from 'scenes/analytics/analyticsUtils'
import { urls } from 'scenes/urls'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType } from '~/queries/schema/schema-general'
import { InsightShortId } from '~/types'

import type {
    SidebarButtonApi,
    SidebarLinkApi,
    SidebarListSourceApi,
    SidebarMetricApi,
    SidebarListApi,
    SidebarSectionApi,
} from 'products/today/frontend/generated/api.schemas'

import { todayAnalyticsLogic } from './todayAnalyticsLogic'
import { TodayAnalyticsMetric } from './TodayAnalyticsMetric'
import { TodayAnalyticsSidebarCustomize } from './TodayAnalyticsSidebarCustomize'
import { SIDEBAR_ICONS, resolveSidebarTarget } from './todayAnalyticsSidebarTargets'
import { TodayPaneRow } from './TodayPaneRow'
import { TodayPaneSearchList } from './TodayPaneSearchList'
import { TodayPaneSection } from './TodayPaneSection'
import { productPreview } from './todayPreviewCards'
import { TodayPreviewTrigger } from './TodayPreviewTrigger'

const AnalyticsSidebarAgentListener = lazyWithRetry(() =>
    import('scenes/analytics/AnalyticsSidebarAgentListener').then((m) => ({ default: m.AnalyticsSidebarAgentListener }))
)

type SidebarItem = SidebarLinkApi | SidebarButtonApi | SidebarMetricApi | SidebarListApi

function AnalyticsItemIcon({ type }: { type: AnalyticsType }): JSX.Element {
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <span style={{ color: ANALYTICS_TYPE_INFO[type].color }}>
            <AnalyticsTypeIcon type={type} />
        </span>
    )
}

/**
 * The Analytics sub-nav, drawn from the person's layout: sections of links, buttons, metrics and the lists PostHog
 * fills. The default layout is one more layout, so it draws the same way.
 */
export function TodayAnalyticsSidebar(): JSX.Element {
    const { fromPostHog, recentAnalytics, searchQuery, matchesSearch, isSectionOpen, sidebarLayout, sidebarFailed } =
        useValues(todayAnalyticsLogic)
    const { toggleSection, setSearchQuery, loadSidebar } = useActions(todayAnalyticsLogic)
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

    const isOpen = (targetPath: string): boolean =>
        path === removeProjectIdIfPresent(targetPath) && (targetPath !== urls.analyticsList() || openFolder === null)

    const listRows = (source: SidebarListSourceApi): JSX.Element[] => {
        switch (source) {
            case 'pinned':
                return pinnedAnalytics
                    .filter((pinned) => matchesSearch(pinned.kind === 'collection' ? pinned.name : pinned.item.name))
                    .map((pinned) =>
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
                    )
            case 'recents':
                return recentAnalytics
                    .filter((item) => matchesSearch(item.name))
                    .map((item) => (
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
                    ))
            case 'by_posthog':
                return fromPostHog
                    .filter((product) => matchesSearch(product.label))
                    .map((product) => {
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
                    })
            default:
                return []
        }
    }

    // An item this version of the app does not know, such as a newer page, draws nothing.
    const itemRows = (section: SidebarSectionApi, item: SidebarItem, index: number): JSX.Element[] => {
        const value = `${section.id}:${index}`
        switch (item.type) {
            case 'list':
                return listRows(item.source)
            case 'metric':
                return matchesSearch(item.label)
                    ? [
                          <TodayAnalyticsMetric
                              key={value}
                              item={item}
                              value={value}
                              active={isOpen(urls.insightView(item.insight as InsightShortId))}
                          />,
                      ]
                    : []
            case 'link': {
                const target = resolveSidebarTarget(item.to, item.label, item.icon)
                if (!target || !matchesSearch(target.label)) {
                    return []
                }
                const row = (
                    <TodayPaneRow
                        value={value}
                        label={target.label}
                        icon={target.icon}
                        to={target.to}
                        active={isOpen(target.path)}
                        dataAttr={`analytics-sidebar-${section.id}`}
                    />
                )
                return [
                    target.explainer ? (
                        <TodayPreviewTrigger key={value} payload={target.explainer}>
                            {row}
                        </TodayPreviewTrigger>
                    ) : (
                        <Fragment key={value}>{row}</Fragment>
                    ),
                ]
            }
            case 'button': {
                const target = resolveSidebarTarget(item.to, item.label, item.icon)
                if (!target || !matchesSearch(target.label)) {
                    return []
                }
                return [
                    <Button
                        key={value}
                        size="sm"
                        variant={item.variant ?? 'outline'}
                        nativeButton={false}
                        render={<LinkPrimitive to={target.to} />}
                        className="my-1 w-full justify-start"
                        data-attr={`analytics-sidebar-${section.id}-button`}
                    >
                        {target.icon}
                        <span className="truncate">{target.label}</span>
                    </Button>,
                ]
            }
            default:
                return []
        }
    }

    // The first heading in the layout sits under the top rows, so it needs no line above it, even when it is hidden.
    const firstHeadingId = sidebarLayout?.sections.find((section) => section.title)?.id
    const sections = (sidebarLayout?.sections ?? [])
        .map((section) => ({ section, rows: section.items.flatMap((item, index) => itemRows(section, item, index)) }))
        .filter(({ rows }) => rows.length > 0)

    return (
        <div className="TodayPane group/colorful-product-icons colorful-product-icons-true" data-quill>
            <TodayPaneSearchList
                query={searchQuery}
                onQueryChange={setSearchQuery}
                searchLabel="Search analytics"
                dataAttr="analytics-sidebar-search"
            >
                {!sidebarLayout ? (
                    sidebarFailed ? (
                        <div className="flex flex-col items-start gap-1 px-2 py-1 text-sm text-muted-foreground">
                            <span>Couldn’t load the Analytics sidebar.</span>
                            <Button
                                size="sm"
                                variant="outline"
                                onClick={loadSidebar}
                                data-attr="analytics-sidebar-retry"
                            >
                                Try again
                            </Button>
                        </div>
                    ) : (
                        <SkeletonText lines={5} className="px-2 py-1" />
                    )
                ) : sections.length === 0 && searchQuery.trim() !== '' ? (
                    <div className="px-2 py-1 text-sm text-muted-foreground">
                        Nothing in Analytics matches your search.
                    </div>
                ) : (
                    sections.map(({ section, rows }) =>
                        section.title ? (
                            <TodayPaneSection
                                key={section.id}
                                label={section.title}
                                icon={section.icon ? SIDEBAR_ICONS[section.icon] : null}
                                open={isSectionOpen(section.id)}
                                count={rows.length}
                                showCount={false}
                                onToggle={() => toggleSection(section.id)}
                                divider={section.id !== firstHeadingId}
                                dataAttr={`analytics-section-${section.id}`}
                            >
                                {rows}
                            </TodayPaneSection>
                        ) : (
                            <div key={section.id} className="flex flex-col gap-px pb-2">
                                {rows}
                            </div>
                        )
                    )
                )}
                <TodayAnalyticsSidebarCustomize />
            </TodayPaneSearchList>
            <Suspense fallback={null}>
                <AnalyticsSidebarAgentListener />
            </Suspense>
        </div>
    )
}
