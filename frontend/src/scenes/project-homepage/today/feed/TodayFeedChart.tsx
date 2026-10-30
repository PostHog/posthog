import { Suspense, lazy } from 'react'

import { Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'
import { retryImport } from 'lib/utils/retryImport'

import { TodayChange } from '../TodayChange'

const TodaySparkline = lazy(() =>
    retryImport(() => import('../TodaySparkline').then((m) => ({ default: m.TodaySparkline })))
)

export function TodayFeedChart({
    label,
    current,
    previous,
    series,
    days,
    to,
    onOpen,
}: {
    label: string
    current: number
    previous: number
    series: number[]
    days: string[]
    to: string
    onOpen: () => void
}): JSX.Element {
    const change = previous > 0 ? ((current - previous) / previous) * 100 : null
    return (
        <LinkPrimitive
            to={to}
            onClick={onOpen}
            className="flex flex-col gap-2 rounded-lg border border-border bg-card p-3 text-card-foreground hover:bg-fill-hover"
            data-attr="today-feed-chart"
        >
            <span className="flex min-w-0 items-baseline justify-between gap-3">
                <Text size="xs" variant="muted" className="truncate">
                    {label}, last 7 days
                </Text>
                <span className="flex shrink-0 items-baseline gap-2">
                    <Text size="sm" weight="semibold" translate="no">
                        {humanFriendlyLargeNumber(current)}
                    </Text>
                    <TodayChange change={change} tone="neutral" />
                </span>
            </span>
            <span className="block h-24" aria-hidden>
                <Suspense fallback={null}>
                    <TodaySparkline values={series} labels={days} emphasizeLast={7} tone="neutral" />
                </Suspense>
            </span>
        </LinkPrimitive>
    )
}
