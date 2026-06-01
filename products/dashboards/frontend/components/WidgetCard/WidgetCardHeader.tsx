import clsx from 'clsx'
import React from 'react'

import { CardMeta } from 'lib/components/Cards/CardMeta'
import { CardTopHeadingRow } from 'lib/components/Cards/CardTopHeadingRow'
import { More, MoreProps } from 'lib/lemon-ui/LemonButton/More'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { dateFilterToText } from 'lib/utils'

import { DashboardPlacement } from '~/types'

import type { DashboardWidgetHeaderLayout, DashboardWidgetHeaderMeta } from '../../widget_types/catalog'

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
    description?: string
    showDescription?: boolean
    loading?: boolean
    showEditingControls?: boolean
    shouldHideMoreButton?: boolean
    moreButtonOverlay?: MoreProps['overlay']
    onDragHandleMouseDown?: React.MouseEventHandler<HTMLDivElement>
}

type WidgetCardHeaderTitleProps = {
    title: string
    defaultTitle?: string
    titleHref?: string
    loading?: boolean
    showEditingControls?: boolean
    headingLevel?: 'h3' | 'h4'
    className?: string
}

function WidgetCardHeaderTitle({
    title,
    defaultTitle,
    titleHref,
    loading,
    showEditingControls,
    headingLevel = 'h4',
    className,
}: WidgetCardHeaderTitleProps): JSX.Element {
    const displayTitle = title || defaultTitle || 'Untitled'
    const Heading = headingLevel

    const titleContent = (
        <>
            <span className={clsx('truncate', titleHref && !showEditingControls && 'text-primary')}>
                {displayTitle}
            </span>
            {loading && (
                <span className={clsx('text-sm font-medium ml-1.5', loading ? 'text-accent' : 'text-muted')}>
                    <Spinner className="mr-1.5 text-base" textColored />
                    Loading
                </span>
            )}
        </>
    )

    const titleEl =
        titleHref && !showEditingControls ? (
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
                titleHref && !showEditingControls && 'inline-flex items-center overflow-visible',
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
    description,
    showDescription = true,
    loading,
    showEditingControls,
    shouldHideMoreButton,
    moreButtonOverlay,
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
            <CardTopHeadingRow typeLabel={widgetTypeLabel} showTypeLabel={showWidgetType} dateText={dateText} />
        ) : null
    const resolvedTopHeading = topHeading !== undefined ? topHeading : derivedTopHeading

    const titleEl = (
        <WidgetCardHeaderTitle
            title={title}
            defaultTitle={defaultTitle}
            titleHref={titleHref}
            loading={loading}
            showEditingControls={showEditingControls}
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
                content={
                    <>
                        {titleEl}
                        {descriptionEl}
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
                        showEditingControls={showEditingControls}
                        headingLevel="h3"
                    />
                </div>
                {!showEditingControls && (
                    <WidgetCardHeaderTitle
                        title={title}
                        defaultTitle={defaultTitle}
                        titleHref={titleHref}
                        loading={loading}
                        showEditingControls={showEditingControls}
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
