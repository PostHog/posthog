import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconRefresh, IconX } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { NotebookNodeProps, NotebookNodeType } from 'scenes/notebooks/types'
import { personLogic } from 'scenes/persons/personLogic'

import { PersonType } from '~/types'

import { customerProfileLogic } from 'products/customer_analytics/frontend/customerProfileLogic'

import { createPostHogWidgetNode } from '../NodeWrapper'
import { notebookNodeLogic } from '../notebookNodeLogic'
import { AISessionSummary } from './AISessionSummary/AISessionSummary'
import { notebookNodePersonFeedLogic } from './notebookNodePersonFeedLogic'
import { Session } from './Session'

const SLOW_LOAD_MS = 15_000

function useSlowLoad(loading: boolean, thresholdMs = SLOW_LOAD_MS): boolean {
    const [isSlow, setIsSlow] = useState(false)
    useEffect(() => {
        if (!loading) {
            setIsSlow(false)
            return
        }
        const timer = setTimeout(() => setIsSlow(true), thresholdMs)
        return () => clearTimeout(timer)
    }, [loading, thresholdMs])
    return isSlow
}

const FeedSkeleton = ({ slow, onRetry }: { slow?: boolean; onRetry?: () => void }): JSX.Element => (
    <div className="deprecated-space-y-4 p-4">
        {slow && onRetry && (
            <div className="flex items-center justify-between gap-2 rounded border border-dashed p-3 text-sm">
                <span>This is taking longer than usual.</span>
                <LemonButton type="secondary" size="small" icon={<IconRefresh />} onClick={onRetry}>
                    Retry
                </LemonButton>
            </div>
        )}
        <LemonSkeleton className="h-8" repeat={10} />
    </div>
)

const FeedLoadError = ({ onRetry }: { onRetry: () => void }): JSX.Element => (
    <div className="flex flex-col items-center justify-center gap-3 p-6 text-center">
        <h3 className="text-base font-semibold mb-0">Could not load session timeline</h3>
        <p className="text-sm text-secondary mb-0">Something went wrong while loading this person's recent sessions.</p>
        <LemonButton type="primary" size="small" icon={<IconRefresh />} onClick={onRetry}>
            Try again
        </LemonButton>
    </div>
)

type FeedProps = {
    person: PersonType
}

const Feed = ({ person }: FeedProps): JSX.Element => {
    const id = person.id ?? 'missing'
    const { sessions, sessionsLoading, sessionsLoadError } = useValues(notebookNodePersonFeedLogic({ personId: id }))
    const { loadSessionsTimeline } = useActions(notebookNodePersonFeedLogic({ personId: id }))
    const slow = useSlowLoad(sessionsLoading && !sessions)

    if (sessionsLoadError && !sessionsLoading) {
        return <FeedLoadError onRetry={() => loadSessionsTimeline()} />
    }

    if (!sessions && sessionsLoading) {
        return <FeedSkeleton slow={slow} onRetry={() => loadSessionsTimeline()} />
    } else if (sessions === null) {
        return <NotFound object="person" />
    }

    return (
        <div className="p-2">
            <AISessionSummary personId={id} />
            <h3 className="font-semibold mb-2">Session timeline</h3>
            {sessions.map((session: any) => (
                <Session key={session.sessionId} session={session} />
            ))}
        </div>
    )
}

const Component = ({ attributes }: NotebookNodeProps<NotebookNodePersonFeedAttributes>): JSX.Element | null => {
    const { id, distinctId } = attributes
    const { expanded, notebookLogic } = useValues(notebookNodeLogic)
    const mountedPersonFeedLogic = notebookNodePersonFeedLogic({ personId: id })
    useAttachedLogic(mountedPersonFeedLogic, notebookLogic)
    const { setMenuItems } = useActions(notebookNodeLogic)
    const { removeNode } = useActions(customerProfileLogic)

    const logic = personLogic({ id, distinctId })
    const { person, personLoading } = useValues(logic)
    const { loadPerson } = useActions(logic)
    const slow = useSlowLoad(personLoading && !person)

    useOnMountEffect(() => {
        setMenuItems([
            {
                label: 'Remove',
                onClick: () => removeNode(NotebookNodeType.PersonFeed),
                sideIcon: <IconX />,
                status: 'danger',
            },
        ])
    })

    if (!expanded) {
        return null
    }

    if (personLoading) {
        return <FeedSkeleton slow={slow} onRetry={() => loadPerson()} />
    } else if (!person) {
        return <NotFound object="person" />
    }

    return <Feed person={person} />
}

type NotebookNodePersonFeedAttributes = {
    id: string
    distinctId: string
}

export const NotebookNodePersonFeed = createPostHogWidgetNode<NotebookNodePersonFeedAttributes>({
    nodeType: NotebookNodeType.PersonFeed,
    titlePlaceholder: 'Feed',
    Component,
    resizeable: false,
    expandable: true,
    startExpanded: true,
    attributes: {
        id: {},
        distinctId: {},
    },
})
