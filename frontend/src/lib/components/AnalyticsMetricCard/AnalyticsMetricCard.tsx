import clsx from 'clsx'
import type { ReactNode } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { LemonSkeleton } from '@posthog/lemon-ui'
import {
    Metric,
    MetricDelta,
    MetricHeader,
    type MetricProps,
    MetricSparkline,
    MetricSubtitle,
    MetricTitle,
    MetricValue,
} from '@posthog/quill-components/metric'

export interface AnalyticsMetricCardProps extends Omit<
    Extract<MetricProps, { series?: undefined }>,
    'children' | 'series'
> {
    title: ReactNode
    /** Render the change pill after the subtitle instead of in the title row. */
    changeBesideSubtitle?: boolean
    loading?: boolean
    error?: ReactNode
    emptyMessage?: ReactNode
    onClick?: () => void
    selected?: boolean
    ariaLabel?: string
    /** Rendered above the clickable area, so it can hold its own buttons. */
    header?: ReactNode
    adornment?: ReactNode
}

/** Shared surface for analytics metrics; pass data/theme for a sparkline and showChange for comparisons. */
export function AnalyticsMetricCard({
    loading = false,
    error,
    emptyMessage = 'No data for this period',
    onClick,
    selected,
    ariaLabel,
    header,
    adornment,
    className,
    dataAttr,
    title,
    changeBesideSubtitle = false,
    ...metricProps
}: AnalyticsMetricCardProps): JSX.Element {
    const Content = onClick ? 'button' : 'div'
    const hasValue = metricProps.value != null || metricProps.data?.some(Number.isFinite)
    const label =
        title != null ? (
            <span className={clsx('inline-flex items-center gap-1', selected && 'text-accent')}>{title}</span>
        ) : null

    return (
        <div
            className={clsx(
                // overflow-hidden clips the edge-to-edge sparkline to the rounded corners, so the focus ring
                // sits on this element rather than on the button inside it.
                'relative flex min-w-0 flex-col overflow-hidden rounded border transition-colors has-[>button:focus-visible]:ring-2 has-[>button:focus-visible]:ring-accent',
                selected ? 'border-accent bg-accent-highlight-secondary' : 'border-primary bg-surface-primary',
                onClick && 'hover:border-accent',
                className
            )}
        >
            {header}
            <Content
                type={onClick ? 'button' : undefined}
                onClick={
                    onClick
                        ? (event) => {
                              event.stopPropagation()
                              onClick()
                          }
                        : undefined
                }
                aria-label={ariaLabel}
                aria-pressed={onClick ? selected : undefined}
                aria-busy={loading}
                data-attr={dataAttr}
                className={clsx(
                    'flex h-full w-full min-w-0 flex-col py-3 text-left',
                    onClick && 'cursor-pointer focus-visible:outline-none'
                )}
            >
                {loading ? (
                    <span className="flex w-full flex-col gap-2 px-3">
                        <LemonSkeleton className="h-3 w-16" />
                        <LemonSkeleton className="h-9 w-24" />
                        <LemonSkeleton className="h-3 w-20" />
                    </span>
                ) : error || !hasValue ? (
                    <span className="flex flex-col px-3">
                        {label && <span className="mb-2 text-sm font-medium">{label}</span>}
                        <span className={clsx('text-sm', error ? 'text-danger' : 'text-secondary')}>
                            {error || emptyMessage}
                        </span>
                    </span>
                ) : (
                    <Metric {...metricProps} className="w-full px-3">
                        {(label || !changeBesideSubtitle) && (
                            // The spare height goes above the headline, so a wrapped title does not move it.
                            <MetricHeader className={clsx(!changeBesideSubtitle && 'flex-1', !label && 'justify-end')}>
                                {label && <MetricTitle>{label}</MetricTitle>}
                                {!changeBesideSubtitle && <MetricDelta />}
                            </MetricHeader>
                        )}
                        {changeBesideSubtitle ? (
                            <>
                                <MetricValue className={clsx(label && 'mt-2')} />
                                {/* The subtitle truncates, so the pill never wraps when hover changes the text width. */}
                                <div className="mt-1 flex flex-1 items-start gap-2">
                                    <MetricSubtitle className="min-w-0 flex-1 truncate" />
                                    <MetricDelta className="ml-auto shrink-0" />
                                </div>
                            </>
                        ) : (
                            <>
                                <MetricValue className="mt-2" />
                                <MetricSubtitle className="mt-1" />
                            </>
                        )}
                        <MetricSparkline className="-mx-3 -mb-3 mt-3" />
                    </Metric>
                )}
                {onClick && selected === undefined && (
                    <IconChevronRight className="absolute bottom-3 right-3 size-3 text-secondary" aria-hidden />
                )}
            </Content>
            {adornment}
        </div>
    )
}
