import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import type { communicationDetailsLogicType } from './CommunicationDetailsLogicType'
import { teamLogic } from 'scenes/teamLogic'
import PostHog from 'posthog-js-lite'
import { userLogic } from 'scenes/userLogic'

export interface CommunicationDetailsLogicProps {
    eventUUID: string | null
}

export const communicationDetailsLogic = kea<communicationDetailsLogicType>([
    path(['scenes', 'events', 'communicationDetailsLogic']),
    props({ eventUUID: null } as CommunicationDetailsLogicProps),
    key((props) => `communicationDetailsLogic-${props.eventUUID}`),
    connect({
        values: [teamLogic, ['currentTeam'], userLogic, ['user']],
    }),
    actions({
        saveNote: (content: string) => ({ content }),
        setReplyType: (type: 'internal' | 'public') => ({ type }),
        setNoteContent: (content: string) => ({ content }),
        sentSuccessfully: true,
        sendingFailed: true,
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
                sentSuccessfully: () => '',
            },
        ],
    }),
    selectors({
        publicReplyEnabled: [(s) => [s.replyType], (type) => type === 'public'],
        posthogSDK: [
            (s) => [s.currentTeam],
            (currentTeam) => {
                if (!currentTeam) {
                    return null
                }
                return new PostHog(currentTeam.api_token, {
                    host: window.JS_POSTHOG_HOST || 'https://app.posthog.com',
                    enable: true,
                    persistence: 'memory', // We don't want to persist anything, all events are in-memory
                    persistence_name: currentTeam.id + '_communications_sdk',
                })
            },
        ],
    }),
    listeners(({ values, actions, props }) => ({
        saveNote: async ({ content }: { content: string }) => {
            // TODO: tests to make sure we don't send emails when toggle is off and do when on
            // TODO: make it send an event to PostHog - should be whatever team we're on ??? -
            const event = values.publicReplyEnabled ? '$communication_email_sent' : '$communication_note_saved'

            if (values.posthogSDK) {
                values.posthogSDK.capture(event, {
                    ...{
                        body_plain: content,
                        subject: `HogDesk Bug Report [${props.eventUUID}]`,
                        from: 'bugs@posthog.com',
                        bug_report_uuid: props.eventUUID,
                    },
                    ...(values.publicReplyEnabled ? { to: values.user?.email || 'unknown' } : {}),
                })
                actions.sentSuccessfully()
            } else {
                actions.sendingFailed()
            }
        },
    })),
])
