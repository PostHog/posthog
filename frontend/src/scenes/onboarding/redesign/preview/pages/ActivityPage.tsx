import clsx from 'clsx'
import { type ComponentType, useEffect, useRef, useState } from 'react'

import {
    IconCalendar,
    IconChevronDown,
    IconClock,
    IconEllipsis,
    IconExternal,
    IconGear,
    IconLive,
    IconPlus,
    IconRefresh,
    IconRewindPlay,
    IconTarget,
} from '@posthog/icons'

import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

import posthogIcon from 'public/posthog-icon.svg'

import { type PreviewEvent } from '../types'

const VISIBLE_ROWS = 11
const STREAM_INTERVAL_MS = 1500

// Real columns, wide on purpose — the preview pane crops the table off the right edge like the app.
const GRID = 'grid grid-cols-[16px_150px_172px_190px_118px_104px_132px] items-center gap-x-2'

type IconComponent = ComponentType<{ className?: string }>

interface FeedRow {
    id: number
    event: PreviewEvent
}

function relativeTime(index: number): string {
    if (index <= 3) {
        return 'a few seconds ago'
    }
    if (index <= 6) {
        return 'a minute ago'
    }
    if (index <= 9) {
        return '2 minutes ago'
    }
    return '5 minutes ago'
}

function Tab({
    Icon,
    label,
    active,
    iconClassName,
}: {
    Icon: IconComponent
    label: string
    active?: boolean
    iconClassName?: string
}): JSX.Element {
    return (
        <div
            className={clsx(
                'flex items-center gap-1.5 border-b-2 py-2 text-xs leading-none',
                active ? 'border-accent font-semibold text-accent' : 'border-transparent text-secondary'
            )}
        >
            <Icon className={clsx('size-3.5', iconClassName)} />
            {label}
        </div>
    )
}

function ControlPill({
    Icon,
    label,
    chevron,
    badge,
}: {
    Icon: IconComponent
    label: string
    chevron?: boolean
    badge?: boolean
}): JSX.Element {
    return (
        <span className="inline-flex shrink-0 items-center gap-1 rounded border border-primary bg-surface-primary px-1.5 py-1 text-xs text-secondary">
            <Icon className="size-3 text-secondary opacity-70" />
            {label}
            {badge && <span className="size-1.5 rounded-full bg-accent" />}
            {chevron && <IconChevronDown className="size-3 opacity-60" />}
        </span>
    )
}

function HeaderCell({ label }: { label: string }): JSX.Element {
    return (
        <span className="flex items-center gap-1 truncate text-xxs font-semibold uppercase tracking-wide text-secondary">
            {label}
            <IconEllipsis className="size-3 shrink-0 opacity-40" />
        </span>
    )
}

/**
 * The preview "Activity" view: a faithful-ish PostHog events table (multi-column, cropping off the right
 * edge) with archetype-themed fake data streaming in over time. Kept static (no timer, no row animation)
 * under Storybook so visual-regression snapshots don't drift.
 */
export function ActivityPage({ events }: { events: PreviewEvent[] }): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()
    const [feed, setFeed] = useState<FeedRow[]>(() =>
        events.slice(0, VISIBLE_ROWS).map((event, i) => ({ id: i, event }))
    )

    // `buildEventFeed` returns a fresh array each render, so read the latest deck from a ref instead of
    // restarting the interval on every new reference.
    const deckRef = useRef(events)
    useEffect(() => {
        deckRef.current = events
    }, [events])

    useEffect(() => {
        if (isStatic) {
            return
        }
        // `cursor` walks the deck; new rows are prepended and the oldest drops off the bottom.
        let cursor = VISIBLE_ROWS
        const intervalId = setInterval(() => {
            const deck = deckRef.current
            if (deck.length === 0) {
                return
            }
            const event = deck[cursor % deck.length]
            const rowId = cursor
            cursor += 1
            setFeed((prev) => [{ id: rowId, event }, ...prev].slice(0, VISIBLE_ROWS))
        }, STREAM_INTERVAL_MS)
        return () => clearInterval(intervalId)
    }, [isStatic])

    return (
        <div className="flex h-full flex-col">
            {/* Tab bar — bleeds to the padded container edges */}
            <div className="-mx-3 -mt-3 flex shrink-0 items-center gap-4 border-b border-primary px-3">
                <Tab Icon={IconClock} label="Events" active />
                <Tab Icon={IconRewindPlay} label="Sessions" iconClassName="text-[#f7a501]" />
                <Tab Icon={IconLive} label="Live" />
            </div>

            <div className="mt-3 flex shrink-0 items-center gap-1.5">
                <IconClock className="size-4 text-accent" />
                <h2 className="text-base font-bold text-default">Activity</h2>
            </div>
            <p className="mt-1 shrink-0 text-xs text-secondary">
                Explore your events or see real-time events from your app or website.
            </p>

            <div className="mt-2.5 flex shrink-0 items-center gap-1.5">
                <ControlPill Icon={IconCalendar} label="Last hour" chevron />
                <ControlPill Icon={IconTarget} label="Select an event" badge />
                <ControlPill Icon={IconPlus} label="Property filters" />
            </div>
            <div className="mt-1.5 flex shrink-0 items-center gap-1.5">
                <ControlPill Icon={IconRefresh} label="Reload" />
                <span className="text-xxs text-tertiary">4.5s</span>
                <span className="ml-auto" />
                <ControlPill Icon={IconGear} label="Configure columns" />
            </div>

            {/* Header — same wide grid as the rows so columns line up and crop together */}
            <div className={clsx(GRID, 'mt-3 shrink-0 border-b border-primary px-1 pb-1.5 pt-1')}>
                <span />
                <HeaderCell label="Event" />
                <HeaderCell label="Person" />
                <HeaderCell label="URL / Screen" />
                <HeaderCell label="Time" />
                <HeaderCell label="Events_count" />
                <HeaderCell label="Analytics_version" />
            </div>

            <div className="min-h-0 flex-1 overflow-hidden">
                {feed.map(({ id, event }, idx) => (
                    <div
                        key={id}
                        className={clsx(GRID, 'border-b border-primary px-1 py-1.5', !isStatic && 'animate-fade-in')}
                    >
                        <span className="flex flex-col items-center justify-center text-tertiary opacity-50">
                            <IconChevronDown className="-mb-1 size-2.5 rotate-180" />
                            <IconChevronDown className="size-2.5" />
                        </span>
                        <span className="flex min-w-0 items-center gap-1.5">
                            {event.recognized && <img src={posthogIcon} alt="" className="size-3.5 shrink-0" />}
                            <span className="truncate text-xs text-default">{event.name}</span>
                        </span>
                        <span className="flex min-w-0 items-center gap-1.5">
                            <span
                                className={clsx(
                                    'flex size-4 shrink-0 items-center justify-center rounded-full text-[8px] font-bold text-white',
                                    event.color
                                )}
                            >
                                {event.initial}
                            </span>
                            <span className="truncate text-xs text-default">{event.person}</span>
                        </span>
                        <span className="flex min-w-0 items-center gap-1 text-xs text-link">
                            {event.url ? (
                                <>
                                    <span className="truncate">{event.url}</span>
                                    <IconExternal className="size-3 shrink-0 opacity-70" />
                                </>
                            ) : (
                                <span className="text-tertiary">—</span>
                            )}
                        </span>
                        <span className="truncate text-xs text-secondary">{relativeTime(idx)}</span>
                        <span className="text-xs text-tertiary">—</span>
                        <span className="text-xs text-tertiary">—</span>
                    </div>
                ))}
            </div>
        </div>
    )
}
