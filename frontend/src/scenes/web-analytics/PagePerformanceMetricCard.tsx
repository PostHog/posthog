import { memo } from 'react'

import { IconInfo, IconTrending } from '@posthog/icons'
import { LemonSkeleton, LemonTag, Tooltip } from '@posthog/lemon-ui'
import { Sparkline } from '@posthog/quill-charts'
import type { ChartTheme } from '@posthog/quill-charts'

import { IconTrendingDown, IconTrendingFlat } from 'lib/lemon-ui/icons'
import { formatPercentage, humanFriendlyLargeNumber } from 'lib/utils/numbers'

const SPARKLINE_HEIGHT = 44

export interface PagePerformanceMetricCardProps {
    label: string
    value: number
    previous: number | null
    changeFromPreviousPct: number | null
    sparkline: number[]
    sparklineLabels: string[]
    color: string
    theme: ChartTheme
    loading: boolean
    /** Says why this number can't be trusted at face value, shown as an icon beside the label. */
    caveat?: string
    'data-attr'?: string
}

function DeltaTag({
    changeFromPreviousPct,
    previous,
}: {
    changeFromPreviousPct: number
    previous: number | null
}): JSX.Element {
    const Icon =
        changeFromPreviousPct === 0 ? IconTrendingFlat : changeFromPreviousPct > 0 ? IconTrending : IconTrendingDown
    const type = changeFromPreviousPct === 0 ? 'muted' : changeFromPreviousPct > 0 ? 'success' : 'danger'
    const tag = (
        <LemonTag type={type} size="small" icon={<Icon />} className="tabular-nums">
            {`${changeFromPreviousPct > 0 ? '+' : ''}${formatPercentage(changeFromPreviousPct)}`}
        </LemonTag>
    )
    if (previous === null) {
        return tag
    }
    return <Tooltip title={`${humanFriendlyLargeNumber(previous)} in the previous period`}>{tag}</Tooltip>
}

// Every prop is referentially stable, so unrelated scene renders shouldn't redraw four sparklines.
export const PagePerformanceMetricCard = memo(function PagePerformanceMetricCard({
    label,
    value,
    previous,
    changeFromPreviousPct,
    sparkline,
    sparklineLabels,
    color,
    theme,
    loading,
    caveat,
    'data-attr': dataAttr,
}: PagePerformanceMetricCardProps): JSX.Element {
    const hasSparkline = sparkline.some((point) => point > 0)

    return (
        <div className="border rounded bg-surface-primary flex flex-col overflow-hidden" data-attr={dataAttr}>
            <div className="flex flex-col gap-1 px-3 pt-3">
                <div className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-1 text-xs font-medium text-secondary truncate">
                        {label}
                        {caveat ? (
                            <Tooltip title={caveat}>
                                <IconInfo className="shrink-0 text-base" />
                            </Tooltip>
                        ) : null}
                    </span>
                    {!loading && changeFromPreviousPct !== null && (
                        <DeltaTag changeFromPreviousPct={changeFromPreviousPct} previous={previous} />
                    )}
                </div>
                {loading ? (
                    <LemonSkeleton className="h-8 w-20 my-0.5" />
                ) : (
                    <div className="text-2xl font-semibold tabular-nums">{humanFriendlyLargeNumber(value)}</div>
                )}
                <div className="text-xs text-secondary">Total</div>
            </div>
            {!loading && hasSparkline && (
                <div className="mt-2">
                    <Sparkline
                        data={sparkline}
                        labels={sparklineLabels}
                        theme={theme}
                        color={color}
                        type="line"
                        height={SPARKLINE_HEIGHT}
                    />
                </div>
            )}
        </div>
    )
})
