import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import type { communicationDetailsLogicType } from './CommunicationDetailsLogicType'

export interface CommunicationDetailsLogicProps {
    eventUUID: string | null
}

export const communicationDetailsLogic = kea<communicationDetailsLogicType>([
    path(['scenes', 'events', 'communicationDetailsLogic']),
    props({ eventUUID: null } as CommunicationDetailsLogicProps),
    key((props) => `communicationDetailsLogic-${props.eventUUID}`),
    actions({
        saveNote: (content: string) => ({ content }),
        setReplyType: (type: 'internal' | 'public') => ({ type }),
        setNoteContent: (content: string) => ({ content }),
    }),
    reducers({
        replyType: [
            'internal' as 'internal' | 'public',
            {
                setReplyType: (_, { type }) => type,
            },
        ],
        noteContent: [
            '',
            {
                setNoteContent: (_, { content }) => content,
            },
        ],
    }),
    selectors({
        publicReplyEnabled: [(s) => [s.replyType], (type) => type === 'public'],
    }),
    listeners({
        saveNote: async ({ content }: { content: string }) => {
            // TODO: tests to make sure we don't send emails when toggle is off and do when on
            console.log(content)
            // TODO: make it send an event to PostHog - should be whatever team we're on ??? -
            // and normally we need to hide these events???
        },
    }),
])
