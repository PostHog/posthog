import { actions, kea, key, listeners, path, props, reducers } from 'kea'

import type { communicationDetailsLogicType } from './CommunicationDetailsLogicType'

export interface CommunicationDetailsLogicProps {
    eventUUID: string | null
}

export const communicationDetailsLogic = kea<communicationDetailsLogicType>([
    path(['scenes', 'events', 'communicationDetailsLogic']),
    props({ eventUUID: null } as CommunicationDetailsLogicProps),
    key((props) => `communicationDetailsLogic-${props.eventUUID}`),
    actions({
        togglePublicReply: (publicReplyEnabled: boolean) => ({ publicReplyEnabled }),
        saveNote: (content: string) => ({ content }),
        setNoteContent: (content: string) => ({ content }),
    }),
    reducers({
        publicReplyEnabled: [
            false,
            {
                togglePublicReply: (previousState) => !previousState,
            },
        ],
        noteContent: [
            '',
            {
                setNoteContent: (_, { content }) => content,
            },
        ],
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
