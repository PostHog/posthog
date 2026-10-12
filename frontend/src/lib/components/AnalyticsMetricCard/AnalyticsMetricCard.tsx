import clsx from 'clsx'
import type { ReactNode } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { LemonSkeleton } from '@posthog/lemon-ui'
import { MetricCard, type MetricCardProps } from '@posthog/quill-charts'

export interface AnalyticsMetricCardProps extends MetricCardProps {
    loading?: boolean
    error?: ReactNode
    emptyMessage?: ReactNode
    onClick?: () => void
    selected?: boolean
    ariaLabel?: string
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
    adornment,
    className,
    dataAttr,
    title,
    ...metricProps
}: AnalyticsMetricCardProps): JSX.Element {
    const Content = onClick ? 'button' : 'div'
    const hasValue = metricProps.value != null || metricProps.data?.some(Number.isFinite)
    const label = <span className={clsx('inline-flex items-center gap-1', selected && 'text-accent')}>{title}</span>

    return (
        <div
            className={clsx(
                'relative flex min-w-0 flex-col rounded border transition-colors',
                selected ? 'border-accent bg-accent-highlight-secondary' : 'border-primary bg-surface-primary',
                onClick && 'hover:border-accent',
                className
            )}
        >
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
                    'flex h-full w-full min-w-0 flex-col rounded p-3 text-left',
                    onClick &&
                        'cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent'
                )}
            >
                {loading ? (
                    <span className="flex w-full flex-col gap-2">
                        <LemonSkeleton className="h-3 w-16" />
                        <LemonSkeleton className="h-9 w-24" />
                        <LemonSkeleton className="h-3 w-20" />
                    </span>
                ) : error || !hasValue ? (
                    <>
                        <span className="mb-2 text-sm font-medium">{label}</span>
                        <span className={clsx('text-sm', error ? 'text-danger' : 'text-secondary')}>
                            {error || emptyMessage}
                        </span>
                    </>
                ) : (
                    <MetricCard {...metricProps} title={label} className="h-full [&>div:first-child]:flex-1" />
                )}
                {onClick && (
                    <IconChevronRight className="absolute bottom-3 right-3 size-3 text-secondary" aria-hidden />
                )}
            </Content>
            {adornment}
        </div>
    )
}
