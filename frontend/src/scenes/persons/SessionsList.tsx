import { LemonButton } from '@posthog/lemon-ui'
import {
    IconAdsClick,
    IconCode,
    IconExclamation,
    IconEyeHidden,
    IconEyeVisible,
    IconUnfoldLess,
    IconUnfoldMore,
} from 'lib/components/icons'
import { keyMapping } from 'lib/components/PropertyKeyInfo'
import { Tooltip } from 'lib/components/Tooltip'
import { dayjs } from 'lib/dayjs'
import { eventToDescription, humanFriendlyDetailedTime, humanFriendlyDuration } from 'lib/utils'
import React, { useState } from 'react'
import { EventType, EventWithActionMatches, SessionRecordingType } from '~/types'

function EventIcon({ event }: { event: EventType }): JSX.Element {
    let Component: React.ComponentType<{ className: string }>
    switch (event.event) {
        case '$pageview':
            Component = IconEyeVisible
            break
        case '$pageleave':
            Component = IconEyeHidden
            break
        case '$autocapture':
            Component = IconAdsClick
            break
        case '$rageclick':
            Component = IconExclamation
            break
        default:
            Component = IconCode
    }
    return (
        <Tooltip title={`${keyMapping.event[event.event]?.label || 'Custom'} event`}>
            <Component className="text-2xl text-muted" />
        </Tooltip>
    )
}
export interface Session {
    id: string
    eventsWithActionMatches: EventWithActionMatches[]
    recordings: SessionRecordingType[]
}

export type FeedEntry = Session | EventWithActionMatches[]

export interface SessionsListProps {
    entries: FeedEntry[]
}

export function PersonFeedList({ entries }: SessionsListProps): JSX.Element {
    return (
        <div className="flex-1 space-y-4">
            {entries.length > 0
                ? entries.map((entry, index) => <FeedEntryBrief key={index} entry={entry} />)
                : "This person hasn't been active yet."}
        </div>
    )
}

function FeedEntryBrief({ entry }: { entry: FeedEntry }): JSX.Element {
    return (
        <div className="FeedEntryBrief relative">
            {Array.isArray(entry) ? (
                <OutOfSessionEventsBrief events={entry} />
            ) : (
                <SessionBrief key={entry.id} session={entry} />
            )}
        </div>
    )
}

function SessionBrief({ session }: { session: Session }): JSX.Element {
    const startTime = dayjs(session.eventsWithActionMatches[session.eventsWithActionMatches.length - 1].event.timestamp)
    const endTime = dayjs(session.eventsWithActionMatches[0].event.timestamp)
    const durationSeconds = endTime.diff(startTime, 'second')

    const [isFolded, setIsFolded] = useState(false)

    return (
        <div className="flex flex-col rounded bg-side border overflow-hidden">
            <div className="flex items-center justify-between pl-2 pr-4 py-2 gap-2 bg-light">
                <div className="flex items-center">
                    <LemonButton
                        icon={isFolded ? <IconUnfoldMore /> : <IconUnfoldLess />}
                        status="stealth"
                        onClick={() => setIsFolded((state) => !state)}
                    />
                    <b className="ml-2">{humanFriendlyDetailedTime(startTime)}</b>
                </div>
                <div className="flex items-center">
                    <span>{humanFriendlyDuration(durationSeconds)}</span>
                </div>
            </div>
            {!isFolded && (
                <div className="p-2 border-t space-y-2">
                    {session.eventsWithActionMatches.map((eventWithActionMatches) => (
                        <EventBrief
                            key={eventWithActionMatches.event.id}
                            event={eventWithActionMatches.event}
                            actions={eventWithActionMatches.actions}
                        />
                    ))}
                </div>
            )}
        </div>
    )
}

function OutOfSessionEventsBrief({ events }: { events: EventWithActionMatches[] }): JSX.Element {
    return (
        <div className="p-2 border rounded border-dashed space-y-2">
            {events.map((event) => (
                <EventBrief key={event.event.id} event={event.event} actions={event.actions} />
            ))}
        </div>
    )
}

function EventBrief({ event }: EventWithActionMatches): JSX.Element {
    return (
        <div className="EventBrief relative flex items-center justify-between border rounded pl-3 pr-4 py-2 gap-4 bg-light">
            <div className="flex items-center">
                <EventIcon event={event} />
                <b className="ml-3">{eventToDescription(event)}</b>
            </div>
            <div className="flex items-center">
                <span>
                    {dayjs(event.timestamp).format('h:mm:ss A')}
                    {/* TODO: +n days */}
                </span>
            </div>
        </div>
    )
}
