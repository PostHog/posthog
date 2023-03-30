import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import type { communicationDetailsLogicType } from './CommunicationDetailsLogicType'
import { teamLogic } from 'scenes/teamLogic'
import PostHog from 'posthog-js-lite'
import { userLogic } from 'scenes/userLogic'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { issueKeyToName, IssueStatusOptions } from 'scenes/issues/issuesLogic'

export interface CommunicationDetailsLogicProps {
    eventUUID: string | null
}

export interface CommunicationMessage {
    event?: string
    body_plain: string
    body_html?: string
    subject: string
    from: string
    to?: string
    bug_report_uuid: string
    timestamp?: string
}

export interface CommunicationResponseItem extends CommunicationMessage {
    event: string
}

export interface CommunicationResponse {
    results: CommunicationResponseItem[]
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
        setIssueStatus: (status: IssueStatusOptions) => ({ status }),
        setNoteContent: (content: string) => ({ content }),
        sentSuccessfully: (message: CommunicationResponseItem) => ({ message }),
        sendingFailed: true,
    }),
    loaders(({ props }) => ({
        communications: {
            loadCommunications: async () => {
                return await api.personCommunications.list({
                    bug_report_uuid: props.eventUUID,
                })
            },
        },
    })),
    reducers({
        communications: {
            sentSuccessfully: (state, { message }) => {
                return {
                    ...state,
                    results: [{ ...message, timestamp: new Date(Date.now()).toISOString() }, ...state.results],
                }
            },
        },
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
        issueStatus: [
            'open' as IssueStatusOptions, // TODO: load the actual status
            {
                setIssueStatus: (_, { status }) => status,
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

            if (values.posthogSDK && props.eventUUID) {
                const messageProperties: CommunicationMessage = {
                    ...{
                        body_plain: content,
                        subject: `HogDesk Bug Report [${props.eventUUID}]`,
                        from: values.user?.email || 'support agent',
                        bug_report_uuid: props.eventUUID,
                    },
                    ...(values.publicReplyEnabled ? { to: values.user?.email || 'unknown' } : {}),
                }

                values.posthogSDK.capture(event, messageProperties)
                actions.sentSuccessfully({ ...messageProperties, event })
            } else {
                actions.sendingFailed()
            }
        },
        setIssueStatus: async ({ status }: { status: IssueStatusOptions }) => {
            const event = '$issue_status_update'
            const actor = values.user?.email || 'support agent'
            if (values.posthogSDK && props.eventUUID) {
                const messageProperties: CommunicationMessage = {
                    ...{
                        body_plain: `Status updated to "${issueKeyToName[status]}" by ${actor}`, // TODO: do on the read side instead
                        subject: `HogDesk Bug Report [${props.eventUUID}]`,
                        status: status,
                        from: actor,
                        bug_report_uuid: props.eventUUID,
                    },
                }

                values.posthogSDK.capture(event, messageProperties)
                actions.sentSuccessfully({ ...messageProperties, event })
            } else {
                actions.sendingFailed()
            }
        },
    })),
])
