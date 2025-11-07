import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { NotebookNodeProps, NotebookNodeType } from 'scenes/notebooks/types'
import { personLogic } from 'scenes/persons/personLogic'

import { PersonType } from '~/types'

import { createPostHogWidgetNode } from '../NodeWrapper'
import { notebookNodeLogic } from '../notebookNodeLogic'
import { AISessionSummary } from './AISessionSummary/AISessionSummary'
import { Session } from './Session'
import { notebookNodePersonFeedLogic } from './notebookNodePersonFeedLogic'

const FeedSkeleton = (): JSX.Element => (
    <div className="deprecated-space-y-4 p-4">
        <LemonSkeleton className="h-8" repeat={10} />
    </div>
)

type FeedProps = {
    person: PersonType
}

const Feed = ({ person }: FeedProps): JSX.Element => {
    const id = person.id ?? 'missing'
    const { sessions, sessionsLoading } = useValues(notebookNodePersonFeedLogic({ personId: id }))

    if (!sessions && sessionsLoading) {
        return <FeedSkeleton />
    } else if (sessions === null) {
        return <NotFound object="person" />
    }

    return (
        <div className="p-2">
            <AISessionSummary personId={id} />
            <h3 className="font-semibold mb-2">Session Timeline</h3>
            {sessions.map((session: any) => (
                <Session key={session.sessionId} session={session} />
            ))}
        </div>
    )
}

const Component = ({ attributes }: NotebookNodeProps<NotebookNodePersonFeedAttributes>): JSX.Element | null => {
    const { id, distinctId } = attributes
    const { expanded } = useValues(notebookNodeLogic)

    const logic = personLogic({ id, distinctId })
    const { person, personLoading } = useValues(logic)

    if (!expanded) {
        return null
    }

    if (personLoading) {
        return <FeedSkeleton />
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
