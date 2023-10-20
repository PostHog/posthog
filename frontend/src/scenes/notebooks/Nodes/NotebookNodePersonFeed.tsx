import { useState } from 'react'
import { useActions, useValues } from 'kea'

import { EventType, NotebookNodeType, PersonType } from '~/types'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeProps } from '../Notebook/utils'
import { notebookNodePersonFeedLogic } from './notebookNodePersonFeedLogic'
import { TimelineEntry } from '~/queries/schema'
import { dayjs } from 'lib/dayjs'
import { LemonButton, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'
import {
    IconExclamation,
    IconEyeHidden,
    IconEyeVisible,
    IconUnfoldLess,
    IconUnfoldMore,
    IconAdsClick,
    IconCode,
} from 'lib/lemon-ui/icons'
import { humanFriendlyDetailedTime, humanFriendlyDuration, eventToDescription } from 'lib/utils'
import { KEY_MAPPING } from 'lib/taxonomy'
import { personLogic } from 'scenes/persons/personLogic'
import { NotFound } from 'lib/components/NotFound'
import { IconRewindPlay } from '@posthog/icons'
import { notebookNodeLogic } from './notebookNodeLogic'

function FeedSkeleton(): JSX.Element {
    return (
        <div className="space-y-4 p-4">
            <LemonSkeleton className="h-8" repeat={10} />
        </div>
    )
}

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
        <Tooltip title={`${KEY_MAPPING.event[event.event]?.label || 'Custom'} event`}>
            <Component className="text-2xl text-muted" />
        </Tooltip>
    )
}

function EventBrief({ event }: { event: EventType }): JSX.Element {
    return (
        <div className="EventBrief relative flex items-center justify-between border rounded pl-3 pr-4 py-2 gap-4 bg-bg-light">
            <div className="flex items-center">
                <EventIcon event={event} />
                <b className="ml-3">{eventToDescription(event)}</b>
            </div>
            <div className="flex items-center">
                <span>{dayjs(event.timestamp).format('h:mm:ss A')}</span>
            </div>
        </div>
    )
}

type SessionProps = {
    session: TimelineEntry
}

const Session = ({ session }: SessionProps): JSX.Element => {
    const { children, nodeId } = useValues(notebookNodeLogic)
    const { updateAttributes } = useActions(notebookNodeLogic)
    const startTime = dayjs(session.events[session.events.length - 1].timestamp)
    const endTime = dayjs(session.events[0].timestamp)
    const durationSeconds = endTime.diff(startTime, 'second')

    const [isFolded, setIsFolded] = useState(false)

    const onOpenReplay = (): void => {
        const newChildren = [...children] || []

        const existingChild = newChildren.find((child) => child.attrs?.nodeId === `${nodeId}-active-replay`)

        if (existingChild) {
            existingChild.attrs.id = session.sessionId
        } else {
            newChildren.splice(0, 0, {
                type: NotebookNodeType.Recording,
                attrs: {
                    id: session.sessionId,
                    nodeId: `${nodeId}-active-replay`,
                    height: '5rem',
                    __init: {
                        expanded: true,
                    },
                },
            })
        }

        updateAttributes({
            children: newChildren,
        })
    }

    return (
        <div className="flex flex-col rounded bg-side border overflow-hidden mb-3" title={session.sessionId}>
            <div className="flex items-center justify-between pl-2 pr-4 py-2 gap-2 bg-bg-light">
                <div className="flex items-center">
                    <LemonButton
                        icon={isFolded ? <IconUnfoldMore /> : <IconUnfoldLess />}
                        status="stealth"
                        onClick={() => setIsFolded((state) => !state)}
                    />
                    <b className="ml-2">{humanFriendlyDetailedTime(startTime)}</b>
                    <span className="text-muted-3000 font-bold ml-1">({session.events.length} events)</span>
                </div>
                <div className="flex items-center flex-1">
                    <span>{humanFriendlyDuration(durationSeconds)}</span>
                </div>
                {session.recording_duration_s ? (
                    <LemonButton icon={<IconRewindPlay />} onClick={() => onOpenReplay()} />
                ) : null}
            </div>
            {!isFolded && (
                <div className="p-2 border-t space-y-2">
                    {session.events.map((event) => (
                        <EventBrief key={event.id} event={event} />
                    ))}
                </div>
            )}
        </div>
    )
}

type FeedProps = {
    person: PersonType
}

const Feed = ({ person }: FeedProps): JSX.Element => {
    const { sessions, sessionsLoading } = useValues(notebookNodePersonFeedLogic({ personId: person.id }))

    if (!sessions && sessionsLoading) {
        return <FeedSkeleton />
    }

    if (sessions === null) {
        return <NotFound object="person" />
    }

    return (
        <div className="p-2">
            {sessions.map((session: TimelineEntry) => (
                <Session key={session.sessionId} session={session} />
            ))}
        </div>
    )
}

const Component = ({ attributes }: NotebookNodeProps<NotebookNodePersonFeedAttributes>): JSX.Element => {
    const { id } = attributes

    const logic = personLogic({ id })
    const { person, personLoading } = useValues(logic)

    if (personLoading) {
        return <FeedSkeleton />
    } else if (!person) {
        return <NotFound object="person" />
    }

    return <Feed person={person} />
}

type NotebookNodePersonFeedAttributes = {
    id: string
}

export const NotebookNodePersonFeed = createPostHogWidgetNode<NotebookNodePersonFeedAttributes>({
    nodeType: NotebookNodeType.PersonFeed,
    titlePlaceholder: 'Feed',
    Component,
    resizeable: false,
    expandable: false,
    attributes: {
        id: {},
    },
})
