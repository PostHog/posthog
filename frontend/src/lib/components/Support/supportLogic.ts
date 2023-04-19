import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { userLogic } from 'scenes/userLogic'

import type { supportLogicType } from './supportLogicType'
import { forms } from 'kea-forms'
import { UserType } from '~/types'
import { uuid } from 'lib/utils'
import posthog from 'posthog-js'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

function getSessionReplayLink(): string {
    const LOOK_BACK = 30
    const recordingStartTime = Math.max(
        Math.floor((new Date().getTime() - (posthog?.sessionManager?._sessionStartTimestamp || 0)) / 1000) - LOOK_BACK,
        0
    )
    const link = `https://app.posthog.com/recordings/${posthog?.sessionRecording?.sessionId}?t=${recordingStartTime}`
    return `\nSession replay: ${link}`
}

function getDjangoAdminLink(user: UserType | null): string {
    if (!user) {
        return ''
    }
    const link = `${window.location.origin}/admin/posthog/user/?q=${user.email}`
    console.log(`\nAdmin link: ${link} (Organization: '${user.organization?.name}'; Project: '${user.team?.name}')`)
    return `\nAdmin link: ${link} (Organization: '${user.organization?.name}'; Project: '${user.team?.name}')`
}

export const TargetAreaToName = {
    analytics: 'Analytics',
    app_performance: 'App Performance',
    apps: 'Apps',
    billing: 'Billing',
    cohorts: 'Cohorts',
    data_management: 'Data Management',
    data_integrity: 'Data Integrity',
    ingestion: 'Events Ingestion',
    experiments: 'Experiments',
    feature_flags: 'Feature Flags',
    login: 'Login',
    signup: 'Sign up / Invites',
    session_reply: 'Session Replay',
}

export type supportTicketTargetArea = keyof typeof TargetAreaToName | null
export type supportTicketKind = 'bug' | 'feedback' | null
export const URLPathToTargetArea: Record<string, supportTicketTargetArea> = {
    insights: 'analytics',
    recordings: 'session_reply',
    dashboard: 'analytics',
    feature_flags: 'feature_flags',
    experiments: 'experiments',
    'web-performance': 'session_reply',
    events: 'analytics',
    'data-management': 'data_management',
    cohorts: 'cohorts',
    annotations: 'analytics',
    persons: 'data_integrity',
    groups: 'data_integrity',
    app: 'apps',
    toolbar: 'analytics',
}

export function getURLPathToTargetArea(pathname: string): supportTicketTargetArea | null {
    const first_part = pathname.split('/')[1]
    return URLPathToTargetArea[first_part] ?? null
}

export const supportLogic = kea<supportLogicType>([
    path(['lib', 'components', 'support', 'supportLogic']),
    connect(() => ({
        values: [userLogic, ['user']],
        actions: [eventUsageLogic, ['reportSupportFormSubmitted']],
    })),
    actions(() => ({
        closeSupportForm: () => true,
        // TODO: can these be combined reasonably?
        openSupportForm: (kind: supportTicketKind = null, target_area: supportTicketTargetArea = null) => ({
            kind,
            target_area,
        }),
        openSupportLoggedOutForm: (
            name: string | null = null,
            email: string | null = null,
            kind: supportTicketKind = null,
            target_area: supportTicketTargetArea = null
        ) => ({ name, email, kind, target_area }),
        submitZendeskTicket: (
            name: string,
            email: string,
            kind: supportTicketKind,
            target_area: supportTicketTargetArea,
            message: string
        ) => ({
            name,
            email,
            kind,
            target_area,
            message,
        }),
    })),
    reducers(() => ({
        isSupportFormOpen: [
            false,
            {
                openSupportForm: () => true,
                openSupportLoggedOutForm: () => true,
                closeSupportForm: () => false,
            },
        ],
    })),
    forms(({ actions }) => ({
        sendSupportRequest: {
            defaults: {} as unknown as {
                kind: supportTicketKind
                target_area: supportTicketTargetArea
                message: string
            },
            errors: ({ message, kind, target_area }) => {
                return {
                    message: !message ? 'Please enter a message' : '',
                    kind: !kind ? 'Please choose' : undefined,
                    target_area: !target_area ? 'Please choose' : undefined,
                }
            },
            submit: async ({ kind, target_area, message }) => {
                const name = userLogic.values.user?.first_name
                const email = userLogic.values.user?.email
                actions.submitZendeskTicket(name || '', email || '', kind, target_area, message)
                actions.closeSupportForm()
                actions.resetSendSupportRequest()
            },
        },
        sendSupportLoggedOutRequest: {
            defaults: {} as unknown as {
                name: string
                email: string
                kind: supportTicketKind
                target_area: supportTicketTargetArea
                message: string
            },
            errors: ({ name, email, message, kind, target_area }) => {
                return {
                    name: !name ? 'Please enter your name' : '', // TODO: make name optional, but pre-fill it if user filled it in the form or remove it completely
                    email: !email ? 'Please enter your email' : '',
                    message: !message ? 'Please enter a message' : '',
                    kind: !kind ? 'Please choose' : undefined,
                    target_area: !target_area ? 'Please choose' : undefined,
                }
            },
            submit: async ({ name, email, kind, target_area, message }) => {
                actions.submitZendeskTicket(name || '', email || '', kind, target_area, message)
                actions.closeSupportForm()
                actions.resetSendSupportLoggedOutRequest()
            },
        },
    })),
    listeners(({ actions }) => ({
        openSupportForm: async ({ kind, target_area }) => {
            actions.resetSendSupportRequest({
                kind,
                target_area: target_area ?? getURLPathToTargetArea(window.location.pathname),
                message: '',
            })
        },
        openSupportLoggedOutForm: async ({ name, email, kind, target_area }) => {
            actions.resetSendSupportLoggedOutRequest({
                name: name ? name : '',
                email: email ? email : '',
                kind: kind ? kind : null,
                target_area: target_area ? target_area : null,
                message: '',
            })
        },
        submitZendeskTicket: async ({ name, email, kind, target_area, message }) => {
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
                            `\nInternal link: http://go/ticketByUUID/${zendesk_ticket_uuid}` +
                            getSessionReplayLink() +
                            getDjangoAdminLink(userLogic.values.user),
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
                    actions.reportSupportFormSubmitted(properties)
                })
                .catch((err) => {
                    console.log(err)
                })
        },
    })),
])
