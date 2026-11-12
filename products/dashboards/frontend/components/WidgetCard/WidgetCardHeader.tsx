import clsx from 'clsx'
import React from 'react'

import { CardMeta } from 'lib/components/Cards/CardMeta'
import { More, MoreProps } from 'lib/lemon-ui/LemonButton/More'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonTableLoader } from 'lib/lemon-ui/LemonTable/LemonTableLoader'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { DashboardPlacement } from '~/types'

import type { DashboardWidgetHeaderLayout, DashboardWidgetHeaderMeta } from '../../widget_types/catalog'
import type { DashboardWidgetSlot } from '../../widgets/registry'
import { WidgetCardTopHeading, type DashboardWidgetTopHeadingProps } from './WidgetCardTopHeading'

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
    /** Live (self-updating) widget type — shows a pulsing "Live" marker where the date range would go. */
    isLive?: boolean
    showEditingControls?: boolean
    shouldHideMoreButton?: boolean
    moreButtonOverlay?: MoreProps['overlay']
    /** Refresh control revealed on tile hover (dashboard_tile layout only); forwarded to CardMeta. */
    refreshControl?: JSX.Element | null
}

type WidgetCardHeaderTitleProps = {
    title: string
    defaultTitle?: string
    titleHref?: string
    loading?: boolean
    headingLevel?: 'h3' | 'h4'
    className?: string
}

function WidgetCardHeaderTitle({
    title,
    defaultTitle,
    titleHref,
    loading,
    headingLevel = 'h4',
    className,
}: WidgetCardHeaderTitleProps): JSX.Element {
    const displayTitle = title || defaultTitle || 'Untitled'
    const Heading = headingLevel
    const linkTitle = !!titleHref

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
    isLive,
    showEditingControls,
    shouldHideMoreButton,
    moreButtonOverlay,
    refreshControl,
}: WidgetCardHeaderProps): JSX.Element {
    const resolvedTopHeading =
        topHeading !== undefined ? (
            topHeading
        ) : (
            <WidgetCardTopHeading
                widgetTypeLabel={widgetTypeLabel}
                config={config}
                headerMeta={headerMeta}
                TopHeading={TopHeading}
                isLive={isLive}
            />
        )

    const titleEl = (
        <WidgetCardHeaderTitle
            title={title}
            defaultTitle={defaultTitle}
            titleHref={titleHref}
            loading={loading}
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
                <div className={clsx('drag-handle cursor-move flex-1 min-w-0', !showEditingControls && 'hidden')}>
                    <WidgetCardHeaderTitle
                        title={title}
                        defaultTitle={defaultTitle}
                        titleHref={titleHref}
                        loading={loading}
                        headingLevel="h3"
                    />
                </div>
                {!showEditingControls && (
                    <WidgetCardHeaderTitle
                        title={title}
                        defaultTitle={defaultTitle}
                        titleHref={titleHref}
                        loading={loading}
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

export function widgetCardShouldHideMoreButton(placement: DashboardPlacement, showEditingControls?: boolean): boolean {
    return placement === DashboardPlacement.Public || showEditingControls === false
}
