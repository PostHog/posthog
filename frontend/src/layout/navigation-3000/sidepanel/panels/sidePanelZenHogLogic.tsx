import { actions, connect, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { supportLogic } from 'lib/components/Support/supportLogic'
import posthog from 'posthog-js'
import { userLogic } from 'scenes/userLogic'

import type { zenHogLogicType } from './sidePanelZenHogLogicType'

// need to load zendesk tickets and provide tools for replying to a given one.

export interface ZendeskTicketEvent {
    // Sync this with the backend's SupportTicketEventSerializer!
    id: number
    created_at: Date
    updated_at: Date
    message: string
    kind: 'user' | 'posthog'
}

export interface ZendeskTicket {
    // Sync this with the backend's SupportTicketSerializer!
    id: number
    created_at: Date
    updated_at: Date
    subject: string
    description: string
    status: 'open' | 'closed'
    urgency: 'low' | 'medium' | 'high'
    events: ZendeskTicketEvent[]
}
// type ZendeskTicketCallback = (tickets: ZendeskTicket[]) => void
// interface ZendeskTicketResponse {
//     tickets: ZendeskTicket[]
// }

export const zenHogLogic = kea<zenHogLogicType>([
    path(['layout', 'navigation-3000', 'sidepanel', 'panels', 'sidePanelZenHogLogic']),
    connect({
        actions: [supportLogic, ['submitZendeskTicket']],
        values: [userLogic, ['user']],
    }),
    actions({
        beginZendeskTicketReply: (ticketId: number) => ({ ticketId }),
        cancelZendeskTicketReply: true,
        submitZendeskTicketReply: (ticketId: number, message: string) => ({ ticketId, message }),
    }),
    loaders(({ values }) => ({
        openZendeskTickets: [
            [] as ZendeskTicket[],
            {
                loadZendeskTickets: async () => {
                    // eslint-disable-next-line no-console
                    console.log('no calls yet')
                    const realTickets = await new Promise((resolve) =>
                        posthog.getTicketsForUser(
                            { user: 'marcus.h@posthog.com', userHash: 'garbage', forceReload: true },
                            (tickets) => {
                                console.log(tickets)
                                return resolve(tickets)
                            }
                        )
                    )
                    // eslint-disable-next-line no-console
                    console.log('api was called')
                    // eslint-disable-next-line no-console
                    console.log('realTickets', realTickets)
                    return await new Promise((resolve) =>
                        resolve([
                            {
                                id: 1,
                                created_at: new Date(),
                                updated_at: new Date(),
                                subject: 'Test ticket 1',
                                description: 'This is the first test ticket',
                                status: 'open',
                                urgency: 'low',
                                events: [
                                    {
                                        id: 1,
                                        created_at: new Date(),
                                        updated_at: new Date(),
                                        message: 'Hello! I have a question.',
                                        kind: 'user',
                                    },
                                    {
                                        id: 2,
                                        created_at: new Date(),
                                        updated_at: new Date(),
                                        message: 'Can you please share your question instead of just saying "hello"?',
                                        kind: 'posthog',
                                    },
                                    {
                                        id: 9,
                                        created_at: new Date(),
                                        updated_at: new Date(),
                                        message: 'I want to do X',
                                        kind: 'user',
                                    },
                                ],
                            },
                            {
                                id: 2,
                                created_at: new Date(),
                                updated_at: new Date(),
                                subject: 'Second ticket',
                                description: 'This ticket is of medium severity',
                                status: 'open',
                                urgency: 'medium',
                                events: [
                                    {
                                        id: 3,
                                        created_at: new Date(),
                                        updated_at: new Date(),
                                        message: 'I am experiencing an issue with your software.',
                                        kind: 'user',
                                    },
                                    {
                                        id: 4,
                                        created_at: new Date(),
                                        updated_at: new Date(),
                                        message: 'We are sorry to hear that, can you provide more details?',
                                        kind: 'posthog',
                                    },
                                ],
                            },
                            {
                                id: 3,
                                created_at: new Date(),
                                updated_at: new Date(),
                                subject: 'Third ticket',
                                description: 'Query about pricing',
                                status: 'open',
                                urgency: 'high',
                                events: [
                                    {
                                        id: 5,
                                        created_at: new Date(),
                                        updated_at: new Date(),
                                        message: 'Can you explain your pricing model?',
                                        kind: 'user',
                                    },
                                    {
                                        id: 6,
                                        created_at: new Date(),
                                        updated_at: new Date(),
                                        message: 'Certainly! We offer several pricing tiers depending on usage.',
                                        kind: 'posthog',
                                    },
                                ],
                            },
                            {
                                id: 4,
                                created_at: new Date(),
                                updated_at: new Date(),
                                subject: 'Fourth ticket',
                                description: 'Feedback about the new feature',
                                status: 'closed',
                                urgency: 'low',
                                events: [
                                    {
                                        id: 7,
                                        created_at: new Date(),
                                        updated_at: new Date(),
                                        message: 'I really like the new feature. Great job!',
                                        kind: 'user',
                                    },
                                    {
                                        id: 8,
                                        created_at: new Date(),
                                        updated_at: new Date(),
                                        message: 'Thank you for your feedback!',
                                        kind: 'posthog',
                                    },
                                ],
                            },
                        ])
                    )
                },
            },
        ],

        activeReplyTicketId: [
            null as number | null,
            {
                submitZendeskTicketReply: async ({ ticketId, message }) => {
                    if (!values.user) {
                        throw new Error('Cannot submit zendesk ticket reply without a user')
                    }
                    if (!values.activeReplyTicketId) {
                        throw new Error('Cannot submit zendesk ticket reply without an active ticket id')
                    }
                    // eslint-disable-next-line no-console
                    console.log('Submitting zendesk ticket reply', ticketId, message)
                    // await supportLogic.asyncActions.submitZendeskTicket({
                    //     name: values.user.first_name,
                    //     email: values.user.email,
                    //     kind: 'reply',
                    //     target_area: 'support',
                    //     urgency: 'low',
                    //     message,
                    // })
                    // TODO this is where we call the POST zendesk ticket API
                    return null
                },
            },
        ],
    })),
    reducers({
        activeReplyTicketId: {
            beginZendeskTicketReply: (_, { ticketId }) => ticketId,
            cancelZendeskTicketReply: () => null,
        },
    }),
])
