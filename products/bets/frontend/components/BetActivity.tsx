import { useState } from 'react'

import { IconCode, IconFlask, IconGraph, IconPiggyBank, IconPullRequest, IconTarget, IconToggle } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { activityDetail, dayLabel } from '~/layout/today/todayWorkItems'
import type { InsightShortId } from '~/types'

import type { BetsActivityApi } from '../generated/api.schemas'
import { BetActivitySkeleton } from './BetActivitySkeleton'

const VISIBLE_ENTRIES = 8

function entryHref(entry: BetsActivityApi): string | null {
    switch (entry.resource) {
        case 'task':
            return urls.taskDetail(entry.resource_id)
        case 'experiment':
            return urls.experiment(Number(entry.resource_id))
        case 'flag':
            return urls.featureFlag(Number(entry.resource_id))
        case 'insight':
            return urls.insightView(entry.resource_id as InsightShortId)
        case 'pull_request':
            return entry.resource_id || null
        default:
            return null
    }
}

function entryIcon(entry: BetsActivityApi): JSX.Element {
    switch (entry.resource) {
        case 'task':
            return <IconCode />
        case 'experiment':
            return <IconFlask />
        case 'flag':
            return <IconToggle />
        case 'insight':
            return <IconGraph />
        case 'pull_request':
            return <IconPullRequest />
        default:
            return /^(Budget|Usage)/.test(entry.title) ? <IconPiggyBank /> : <IconTarget />
    }
}

function groupByDay(entries: BetsActivityApi[]): { key: string; label: string; entries: BetsActivityApi[] }[] {
    const now = dayjs()
    const groups: { key: string; label: string; entries: BetsActivityApi[] }[] = []
    for (const entry of entries) {
        const time = dayjs(entry.at)
        const key = time.format('YYYY-MM-DD')
        const last = groups.at(-1)
        if (last?.key === key) {
            last.entries.push(entry)
        } else {
            groups.push({ key, label: dayLabel(time, now), entries: [entry] })
        }
    }
    return groups
}

function ActivityEntry({ entry }: { entry: BetsActivityApi }): JSX.Element {
    const href = entryHref(entry)
    const age = activityDetail(entry.at)
    const external = entry.resource === 'pull_request'
    return (
        <li className="Bets__activityEntry grid gap-2.5">
            <span className="Bets__activityIcon flex" aria-hidden>
                {entryIcon(entry)}
            </span>
            <span
                className="Bets__activityText"
                title={entry.detail ? `${entry.title} · ${entry.detail}` : entry.title}
            >
                {href ? (
                    <LinkPrimitive
                        to={href}
                        target={external ? '_blank' : undefined}
                        className="Bets__activityTitle overflow-hidden text-ellipsis"
                    >
                        {entry.title}
                    </LinkPrimitive>
                ) : (
                    <span className="Bets__activityTitle overflow-hidden text-ellipsis">{entry.title}</span>
                )}
                {entry.detail && (
                    <span className="Bets__activityDetail max-w-full min-w-0 overflow-hidden text-ellipsis">
                        {entry.detail}
                    </span>
                )}
            </span>
            {age && (
                <time
                    className="Bets__activityTime whitespace-nowrap tabular-nums"
                    dateTime={entry.at}
                    title={age.title}
                >
                    {age.text}
                </time>
            )}
        </li>
    )
}

export function BetActivity({
    entries,
    loading,
    error,
    onRefresh,
}: {
    entries: BetsActivityApi[] | null
    loading: boolean
    error: string | null
    onRefresh: () => void
}): JSX.Element {
    const [showAll, setShowAll] = useState(false)
    const visible = entries && !showAll ? entries.slice(0, VISIBLE_ENTRIES) : entries
    return (
        <section className="Bets__activity flex min-w-0 flex-col gap-3" aria-labelledby="bets-activity-title">
            <h2 id="bets-activity-title" className="Bets__sectionTitle">
                Activity
            </h2>
            {error && entries === null ? (
                <div className="flex flex-wrap items-center gap-2">
                    <Text size="sm" variant="destructive" render={<p role="alert" className="m-0" />}>
                        {error}
                    </Text>
                    <Button size="sm" variant="outline" loading={loading} onClick={onRefresh}>
                        Try again
                    </Button>
                </div>
            ) : entries === null || visible === null ? (
                <div aria-busy="true">
                    <BetActivitySkeleton />
                </div>
            ) : !entries.length ? (
                <Text size="sm" variant="muted" render={<p className="m-0" />}>
                    Nothing has happened on this bet yet.
                </Text>
            ) : (
                <>
                    {error && (
                        <Text size="xs" variant="destructive" render={<p role="alert" className="m-0" />}>
                            {error}
                        </Text>
                    )}
                    {groupByDay(visible).map((group) => (
                        <div key={group.key} className="flex flex-col gap-0.5">
                            <h3 className="Bets__activityDayLabel mx-0 mt-0 mb-0.5 font-medium">{group.label}</h3>
                            <ol className="m-0 list-none p-0">
                                {group.entries.map((entry) => (
                                    <ActivityEntry key={entry.id} entry={entry} />
                                ))}
                            </ol>
                        </div>
                    ))}
                    {entries.length > VISIBLE_ENTRIES && (
                        <Button
                            size="inline"
                            variant="link-muted"
                            className="self-start text-xs"
                            aria-expanded={showAll}
                            onClick={() => setShowAll(!showAll)}
                        >
                            {showAll ? 'Show less' : `Show all ${entries.length}`}
                        </Button>
                    )}
                </>
            )}
        </section>
    )
}
