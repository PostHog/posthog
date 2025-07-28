import { LemonSkeleton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { NotFound } from 'lib/components/NotFound'
import { personLogic } from 'scenes/persons/personLogic'

import { createPostHogWidgetNode } from '../NodeWrapper'
import { notebookNodePersonFeedLogic } from './notebookNodePersonFeedLogic'
import { Session } from './Session'
import { PersonType } from '~/types'
import { NotebookNodeProps, NotebookNodeType } from 'scenes/notebooks/types'

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
            {sessions.map((session: any) => (
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
