import { Minus, TrendingDown, TrendingUp } from 'lucide-react'
import { ReactNode } from 'react'

import { ErrorResponse, OverviewResponse, OverviewResponseItem, OverviewResponseKey } from '../types/schemas'
import { cn, formatChangePercentage, formatNumber, getTooltipContent } from '../utils'
import { EmbedSkeleton } from './ui/embedSkeleton'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from './ui/tooltip'

interface OverviewProps {
    response?: OverviewResponse
    loading?: boolean
    error?: ErrorResponse
    className?: string
    onClick?: (key: OverviewResponseKey) => void
}

interface OverviewCardProps {
    item: OverviewResponseItem
    onClick?: (key: OverviewResponseKey) => void
    className?: string
}

function OverviewCard({ item, onClick, className }: OverviewCardProps): ReactNode {
    const { value, previousValue, format, isIncreaseGood, label, changePercentage } = item

    const isClickable = !!onClick
    const hasChange = previousValue != null && changePercentage != null
    const isPositiveChange = hasChange && changePercentage > 0
    const isNeutralChange = hasChange && changePercentage === 0

    // Determine the sentiment color
    let changeColorClass = 'analytics-metric-neutral'
    if (hasChange && !isNeutralChange) {
        const isGoodChange = (isPositiveChange && isIncreaseGood) || (!isPositiveChange && !isIncreaseGood)
        changeColorClass = isGoodChange ? 'analytics-metric-positive' : 'analytics-metric-negative'
    }

    const handleClick = onClick
        ? () => {
              onClick(item.key)
          }
        : undefined

    const renderTrendIcon = (): ReactNode => {
        if (!hasChange || isNeutralChange) {
            return <Minus className="h-4 w-4" />
        }
        return isPositiveChange ? <TrendingUp className="h-4 w-4" /> : <TrendingDown className="h-4 w-4" />
    }

    const tooltipContent = getTooltipContent(value, previousValue, changePercentage, format)

    const content = (
        <div
            className={cn(
                'analytics-metric-card',
                isClickable && 'cursor-pointer hover:bg-accent/50 transition-colors',
                className
            )}
            onClick={handleClick}
        >
            <div className="space-y-2">
                {/* Label */}
                <div className="text-sm text-muted-foreground">{label}</div>

                {/* Main Value */}
                <div className="text-2xl font-bold tabular-nums">{formatNumber(value, format, true)}</div>

                {/* Change Indicator */}
                {hasChange && (
                    <div className={cn('flex items-center gap-1 text-sm', changeColorClass)}>
                        {renderTrendIcon()}
                        <span className="tabular-nums">{formatChangePercentage(changePercentage)}</span>
                    </div>
                )}
            </div>
        </div>
    )

    return (
        <TooltipProvider>
            <Tooltip>
                <TooltipTrigger asChild>{content}</TooltipTrigger>
                <TooltipContent>
                    <p className="text-sm">{tooltipContent}</p>
                </TooltipContent>
            </Tooltip>
        </TooltipProvider>
    )
}

function OverviewCardSkeleton({ className }: { className?: string }): ReactNode {
    return (
        <div className={cn('analytics-metric-card', className)}>
            <div className="space-y-2">
                <EmbedSkeleton className="h-4 w-20" />
                <EmbedSkeleton className="h-8 w-16" />
                <div className="flex items-center gap-1">
                    <EmbedSkeleton className="h-4 w-4" />
                    <EmbedSkeleton className="h-4 w-12" />
                </div>
            </div>
        </div>
    )
}

function OverviewError({ error, className }: { error: ErrorResponse; className?: string }): ReactNode {
    return (
        <div className={cn('analytics-error', className)}>
            <p className="font-medium">Error loading metrics</p>
            <p className="text-xs mt-1">{error.error}</p>
            {error.details && <p className="text-xs mt-1 opacity-75">{error.details}</p>}
        </div>
    )
}

export function Overview({ response, loading = false, error, className, onClick }: OverviewProps): ReactNode {
    if (error) {
        return <OverviewError error={error} className={className} />
    }

    if (loading) {
        return (
            <div className={cn('grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4', className)}>
                {Array.from({ length: 4 }).map((_, i) => (
                    <OverviewCardSkeleton key={i} />
                ))}
            </div>
        )
    }

    if (!response || Object.keys(response).length === 0) {
        return (
            <div className={cn('analytics-error', className)}>
                <p>No metrics available</p>
            </div>
        )
    }

    return (
        <div className={cn('grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4', className)}>
            {Object.values(response).map((item) => (
                <OverviewCard key={item.key} item={item} onClick={onClick} />
            ))}
        </div>
    )
}

export type { OverviewProps }
