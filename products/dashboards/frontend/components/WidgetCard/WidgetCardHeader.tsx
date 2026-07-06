import clsx from 'clsx'
import React, { Suspense } from 'react'

import { CardMeta } from 'lib/components/Cards/CardMeta'
import { CardTopHeadingRow } from 'lib/components/Cards/CardTopHeadingRow'
import { More, MoreProps } from 'lib/lemon-ui/LemonButton/More'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonTableLoader } from 'lib/lemon-ui/LemonTable/LemonTableLoader'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { dateFilterToText } from 'lib/utils/dateFilters'

import { DashboardPlacement } from '~/types'

import type { DashboardWidgetHeaderLayout, DashboardWidgetHeaderMeta } from '../../widget_types/catalog'
import type { DashboardWidgetSlot } from '../../widgets/registry'

/** Props a widget type's optional TopHeading override receives so it can compose its own
 * CardTopHeadingRow — e.g. resolving a saved filter's name the generic header can't derive from config. */
export type DashboardWidgetTopHeadingProps = {
    config: Record<string, unknown>
    widgetTypeLabel?: string
    showWidgetType: boolean
    dateText?: string | null
}

export type WidgetCardHeaderProps = {
    layout: DashboardWidgetHeaderLayout
    title: string
    defaultTitle?: string
    titleHref?: string
    /** Explicit top heading node — used by story fixtures. Otherwise derived from catalog fields below. */
    topHeading?: React.ReactNode
    widgetTypeLabel?: string
    config?: Record<string, unknown>
    headerMeta?: DashboardWidgetHeaderMeta
    /** Optional per-widget-type top heading row; falls back to the type + date range when absent.
     * A `DashboardWidgetSlot` so the registry can code-split it (rendered inside a Suspense below). */
    TopHeading?: DashboardWidgetSlot<DashboardWidgetTopHeadingProps>
    description?: string
    showDescription?: boolean
    loading?: boolean
    showEditingControls?: boolean
    /** When true, title is plain text so drag on the header does not compete with navigation. */
    isDashboardEditMode?: boolean
    shouldHideMoreButton?: boolean
    moreButtonOverlay?: MoreProps['overlay']
    /** Refresh control revealed on tile hover (dashboard_tile layout only); forwarded to CardMeta. */
    refreshControl?: JSX.Element | null
    onDragHandleMouseDown?: React.MouseEventHandler<HTMLDivElement>
}

type WidgetCardHeaderTitleProps = {
    title: string
    defaultTitle?: string
    titleHref?: string
    loading?: boolean
    isDashboardEditMode?: boolean
    headingLevel?: 'h3' | 'h4'
    className?: string
}

function WidgetCardHeaderTitle({
    title,
    defaultTitle,
    titleHref,
    loading,
    isDashboardEditMode,
    headingLevel = 'h4',
    className,
}: WidgetCardHeaderTitleProps): JSX.Element {
    const displayTitle = title || defaultTitle || 'Untitled'
    const Heading = headingLevel
    const linkTitle = !!titleHref && !isDashboardEditMode

    const titleContent = (
        <>
            <span className={clsx('truncate', linkTitle && 'text-primary')}>{displayTitle}</span>
            {loading && (
                <span className={clsx('text-sm font-medium ml-1.5', loading ? 'text-accent' : 'text-muted')}>
                    <Spinner className="mr-1.5 text-base" textColored />
                    Loading
                </span>
            )}
        </>
    )

    const titleEl = linkTitle ? (
        <Link to={titleHref} className="max-w-full truncate">
            {titleContent}
        </Link>
    ) : (
        titleContent
    )

    return (
        <Heading
            title={displayTitle}
            data-attr="widget-card-title"
            data-slot="widget-card-header-title"
            className={clsx(
                linkTitle && 'inline-flex items-center overflow-visible',
                headingLevel === 'h3' && 'truncate text-sm font-semibold m-0',
                className
            )}
        >
            {titleEl}
        </Heading>
    )
}

type WidgetCardHeaderDescriptionProps = {
    description?: string
    showDescription?: boolean
    /** Compact CardMeta header — extra spacing above markdown description. */
    compact?: boolean
}

export function WidgetCardHeaderDescription({
    description,
    showDescription = true,
    compact = false,
}: WidgetCardHeaderDescriptionProps): JSX.Element | null {
    if (!showDescription || !description) {
        return null
    }

    return (
        <div
            className={clsx(
                'min-w-0 max-h-24 w-full max-w-full self-stretch overflow-y-auto break-words [overflow-wrap:anywhere]',
                compact && 'mt-1'
            )}
            data-slot="widget-card-header-description"
        >
            <LemonMarkdown className="CardMeta__description" lowKeyHeadings>
                {description}
            </LemonMarkdown>
        </div>
    )
}

type WidgetCardHeaderActionsProps = {
    loading?: boolean
    shouldHideMoreButton?: boolean
    moreButtonOverlay?: MoreProps['overlay']
    showLoadingSpinner?: boolean
}

function WidgetCardHeaderActions({
    loading,
    shouldHideMoreButton,
    moreButtonOverlay,
    showLoadingSpinner,
}: WidgetCardHeaderActionsProps): JSX.Element {
    return (
        <div data-slot="widget-card-header-actions" className="flex items-center gap-1">
            {showLoadingSpinner && loading && <Spinner />}
            {!shouldHideMoreButton && moreButtonOverlay && <More overlay={moreButtonOverlay} />}
        </div>
    )
}

export function WidgetCardHeader({
    layout,
    title,
    defaultTitle,
    titleHref,
    topHeading,
    widgetTypeLabel,
    config,
    headerMeta,
    TopHeading,
    description,
    showDescription = true,
    loading,
    showEditingControls,
    isDashboardEditMode,
    shouldHideMoreButton,
    moreButtonOverlay,
    refreshControl,
    onDragHandleMouseDown,
}: WidgetCardHeaderProps): JSX.Element {
    const showWidgetType = headerMeta?.showWidgetType ?? true
    const showDateRange = headerMeta?.showDateRange ?? false
    const dateText =
        widgetTypeLabel && showDateRange
            ? widgetDateRangeToText(config?.dateRange as Record<string, unknown> | null | undefined)
            : null
    const derivedTopHeading =
        widgetTypeLabel && (showWidgetType || dateText) ? (
            // A widget type can supply its own top heading row (e.g. session replay surfaces the active
            // saved filter name in place of the now-overridden date range); otherwise fall back to the
            // type + date range.
            TopHeading ? (
                <Suspense fallback={null}>
                    <TopHeading
                        config={config ?? {}}
                        widgetTypeLabel={widgetTypeLabel}
                        showWidgetType={showWidgetType}
                        dateText={dateText}
                    />
                </Suspense>
            ) : (
                <CardTopHeadingRow typeLabel={widgetTypeLabel} showTypeLabel={showWidgetType} dateText={dateText} />
            )
        ) : null
    const resolvedTopHeading = topHeading !== undefined ? topHeading : derivedTopHeading

    const titleEl = (
        <WidgetCardHeaderTitle
            title={title}
            defaultTitle={defaultTitle}
            titleHref={titleHref}
            loading={loading}
            isDashboardEditMode={isDashboardEditMode}
            headingLevel="h4"
        />
    )

    const descriptionEl = (
        <WidgetCardHeaderDescription
            description={description}
            showDescription={showDescription}
            compact={layout === 'dashboard_tile'}
        />
    )

    const actions = (
        <WidgetCardHeaderActions
            loading={loading}
            shouldHideMoreButton={shouldHideMoreButton}
            moreButtonOverlay={moreButtonOverlay}
            showLoadingSpinner={layout === 'simple'}
        />
    )

    if (layout === 'dashboard_tile') {
        return (
            <CardMeta
                compact
                className="WidgetCard__header rounded-b-none"
                showEditingControls={!shouldHideMoreButton && !!moreButtonOverlay}
                topHeading={(resolvedTopHeading as JSX.Element | null) ?? null}
                onMouseDown={showEditingControls ? onDragHandleMouseDown : undefined}
                moreButtons={moreButtonOverlay as JSX.Element | undefined}
                refreshControl={refreshControl}
                content={
                    <>
                        {titleEl}
                        {descriptionEl}
                        <LemonTableLoader loading={loading} />
                    </>
                }
            />
        )
    }

    return (
        <div
            data-slot="widget-card-header"
            className="WidgetCard__header flex flex-col p-4 pb-2 min-w-0 overflow-hidden"
        >
            <div className="flex flex-row items-center gap-2">
                <div
                    className={clsx('drag-handle cursor-move flex-1 min-w-0', !showEditingControls && 'hidden')}
                    onMouseDown={onDragHandleMouseDown}
                >
                    <WidgetCardHeaderTitle
                        title={title}
                        defaultTitle={defaultTitle}
                        titleHref={titleHref}
                        loading={loading}
                        isDashboardEditMode={isDashboardEditMode}
                        headingLevel="h3"
                    />
                </div>
                {!showEditingControls && (
                    <WidgetCardHeaderTitle
                        title={title}
                        defaultTitle={defaultTitle}
                        titleHref={titleHref}
                        loading={loading}
                        isDashboardEditMode={isDashboardEditMode}
                        headingLevel="h3"
                        className="flex-1"
                    />
                )}
                {actions}
            </div>
            {descriptionEl}
        </div>
    )
}

function widgetDateRangeToText(
    dateRange: Record<string, unknown> | null | undefined,
    defaultValue: string | null = 'Last 7 days'
): string | null {
    if (!dateRange || typeof dateRange !== 'object') {
        return defaultValue
    }

    const dateFrom = 'date_from' in dateRange ? (dateRange.date_from as string | null | undefined) : undefined
    const dateTo = 'date_to' in dateRange ? (dateRange.date_to as string | null | undefined) : undefined

    if (!dateFrom && !dateTo) {
        return defaultValue
    }

    return dateFilterToText(dateFrom, dateTo, defaultValue)
}

export function widgetCardShouldHideMoreButton(placement: DashboardPlacement, showEditingControls?: boolean): boolean {
    return placement === DashboardPlacement.Public || showEditingControls === false
}
