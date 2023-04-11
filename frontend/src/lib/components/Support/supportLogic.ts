import { kea } from 'kea'
import { uuid } from 'lib/utils'
import posthog from 'posthog-js'
import { userLogic } from 'scenes/userLogic'

import type { supportLogicType } from './supportLogicType'

export const supportLogic = kea<supportLogicType>({
    path: () => ['lib', 'components', 'support', 'supportLogic'],
    connect: () => ({
        values: [userLogic, ['user']],
    }),
    actions: () => ({
        closeSupportForm: () => true,
        openSupportForm: () => true,
        submitZendeskTicket: (kind: string, target_area: string, message: string) => ({ kind, target_area, message }),
    }),
    reducers: () => ({
        isSupportFormOpen: [
            false,
            {
                openSupportForm: () => true,
                closeSupportForm: () => false,
            },
        ],
    }),
    forms: ({ actions }) => ({
        sendSupportRequest: {
            defaults: {
                kind: undefined as string | undefined, // bug, feedback, question
                target_area: undefined as string | undefined, // session_replay, billing, ...
                message: '',
            },
            errors: ({ message, kind, target_area }) => {
                return {
                    message: !message ? 'Please enter a message' : null,
                    kind: !kind ? 'Please choose' : null,
                    target_area: !target_area ? 'Please choose' : null,
                }
            },
            submit: async ({ kind, target_area, message }: { kind: string; target_area: string; message: string }) => {
                actions.submitZendeskTicket(kind, target_area, message)
                actions.closeSupportForm()
                // TODO: reset values to empty
            },
        },
    }),
    listeners: ({}) => ({
        submitZendeskTicket: async ({ kind, target_area, message }) => {
            const name = userLogic.values.user?.first_name
            const email = userLogic.values.user?.email

            const zendesk_ticket_uuid = uuid()
            const payload = {
                request: {
                    requester: { name: name, email: email },
                    subject: 'Help in-app',
                    comment: {
                        body:
                            message +
                            `\n\n-----` +
                            `\nKind: ${kind}` +
                            `\nTarget area: ${target_area}` +
                            `\nInternal link: http://go/ticketByUUID/${zendesk_ticket_uuid}`,
                    },
                },
            }
            await fetch('https://posthoghelp.zendesk.com/api/v2/requests.json', {
                method: 'POST',
                body: JSON.stringify(payload, undefined, 4),
                headers: { 'Content-Type': 'application/json' },
            })
                .then((res) => res.json())
                .then((res) => {
                    const zendesk_ticket_id = res.request.id
                    const properties = {
                        zendesk_ticket_uuid,
                        kind,
                        target_area,
                        message,
                        zendesk_ticket_id,
                        zendesk_ticket_link: `https://posthoghelp.zendesk.com/agent/tickets/${zendesk_ticket_id}`,
                    }
                    posthog.capture('support_ticket', properties)
                })
                .catch((err) => {
                    console.log(err)
                })
        },
    }),
})
