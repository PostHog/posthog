import { useContext } from 'react'

import { Button, Text } from '@posthog/quill'

import { FilterControlsContext } from '../../filters/filtersContext'

const DAYS = 7
const HOURS = 24

function eventsAt(daysAgo: number, hour: number): number {
    const workday = (daysAgo + 2) % 7 < 5 ? 1 : 0.35
    const daytime = Math.max(0, Math.sin(((hour - 6) / 16) * Math.PI))
    return Math.round(400 * workday * daytime + ((daysAgo * 31 + hour * 17) % 40))
}

function dayLabel(daysAgo: number): string {
    if (daysAgo === 0) {
        return 'Today'
    }
    return daysAgo === 1 ? 'Yesterday' : `${daysAgo} days ago`
}

function dayRange(daysAgo: number): { from: string; to: string } {
    return { from: `now-${daysAgo + 1}d`, to: daysAgo === 0 ? 'now' : `now-${daysAgo}d` }
}

// TODO(2026-11-26): Delete with the kitchen sink fixture, once a product drives its filters from its own custom content.
// Tailwind only builds class names it finds whole in the source, so each shade is written out.
const SHADES = [
    'bg-[color-mix(in_oklab,var(--color-blue-500)_5%,transparent)]',
    'bg-[color-mix(in_oklab,var(--color-blue-500)_25%,transparent)]',
    'bg-[color-mix(in_oklab,var(--color-blue-500)_45%,transparent)]',
    'bg-[color-mix(in_oklab,var(--color-blue-500)_65%,transparent)]',
    'bg-[color-mix(in_oklab,var(--color-blue-500)_85%,transparent)]',
]

export function ActivityHeatmap(): JSX.Element {
    const { timeRange } = useContext(FilterControlsContext)
    const max = Math.max(...Array.from({ length: HOURS }, (_, hour) => eventsAt(0, hour)), 1)
    return (
        <div className="flex h-full flex-col gap-1">
            {Array.from({ length: DAYS }, (_, daysAgo) => {
                const range = dayRange(daysAgo)
                const picked = timeRange?.value?.from === range.from && timeRange.value.to === range.to
                return (
                    <div key={daysAgo} className="flex flex-1 items-center gap-2">
                        <Button
                            size="xs"
                            variant={picked ? 'outline' : 'default'}
                            className="w-24 justify-start"
                            aria-pressed={picked}
                            disabledReason={timeRange ? undefined : 'This dashboard has no time range'}
                            data-attr="dashboard-v2-example-heatmap-day"
                            onClick={() => timeRange?.onChange(picked ? undefined : range)}
                        >
                            {dayLabel(daysAgo)}
                        </Button>
                        <div className="grid h-full flex-1 grid-cols-[repeat(24,minmax(0,1fr))] gap-px">
                            {Array.from({ length: HOURS }, (_, hour) => {
                                const events = eventsAt(daysAgo, hour)
                                return (
                                    <div
                                        key={hour}
                                        title={`${dayLabel(daysAgo)}, ${hour}:00: ${events} events`}
                                        className={`rounded-xs ${SHADES[Math.round((events / max) * (SHADES.length - 1))]}`}
                                    />
                                )
                            })}
                        </div>
                    </div>
                )
            })}
            <Text size="xs" variant="muted">
                Pick a day to narrow the dashboard to it.
            </Text>
        </div>
    )
}
