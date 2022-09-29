import { LemonButton } from '@posthog/lemon-ui'
import { IconEyeVisible, IconUnfoldLess, IconUnfoldMore } from 'lib/components/icons'
import { dayjs } from 'lib/dayjs'
import { eventToDescription, humanFriendlyDetailedTime, humanFriendlyDuration } from 'lib/utils'
import React, { useState } from 'react'
import { EventWithActionMatches, SessionRecordingType } from '~/types'

export interface Session {
    id: string
    eventsWithActionMatches: EventWithActionMatches[]
    recordings: SessionRecordingType[]
}

export interface SessionsListProps {
    sessions: Session[]
}

export function SessionsList({ sessions }: SessionsListProps): JSX.Element {
    return (
        <div>
            {sessions.length > 0
                ? sessions.map((session) => <SessionBrief key={session.id} session={session} />)
                : "This person hasn't been active yet."}
        </div>
    )
}

function SessionBrief({ session }: { session: Session }): JSX.Element {
    const startTime = dayjs(session.eventsWithActionMatches[0].event.timestamp)
    const endTime = dayjs(session.eventsWithActionMatches[session.eventsWithActionMatches.length - 1].event.timestamp)
    const durationSeconds = endTime.diff(startTime, 'second')

    const [isFolded, setIsFolded] = useState(false)

    return (
        <div className="flex flex-col rounded bg-side border overflow-hidden">
            <div className="flex items-center justify-between p-2 gap-2 bg-light">
                <div className="flex items-center">
                    <LemonButton
                        icon={isFolded ? <IconUnfoldMore /> : <IconUnfoldLess />}
                        status="stealth"
                        onClick={() => setIsFolded((state) => !state)}
                    />
                    <b className="ml-2">{humanFriendlyDetailedTime(startTime)}</b>
                </div>
                <div className="flex items-center mr-2">
                    <span>{humanFriendlyDuration(durationSeconds)}</span>
                </div>
            </div>
            {!isFolded && (
                <div className="p-2 border-t">
                    {session.eventsWithActionMatches.map((eventWithActionMatches, index) => (
                        <div key={eventWithActionMatches.event.id} className="flex flex-col">
                            <div className="flex flex-col">
                                <div className="flex items-center justify-between border rounded px-3 py-2 gap-4 bg-light">
                                    <div className="flex items-center">
                                        <IconEyeVisible className="text-2xl text-muted" />
                                        <b className="ml-3">{eventToDescription(eventWithActionMatches.event)}</b>
                                    </div>
                                    <div className="flex items-center mr-2">
                                        <span>
                                            {dayjs(eventWithActionMatches.event.timestamp).format('h:mm:ss A')}
                                            {/* TODO: +n days */}
                                        </span>
                                    </div>
                                </div>
                            </div>
                            {index < session.eventsWithActionMatches.length - 1 && (
                                <div className="h-2 w-0 border-l ml-6" />
                            )}
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}
