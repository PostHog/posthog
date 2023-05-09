import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { uuid } from 'lib/utils'
import posthog from 'posthog-js'
import { userLogic } from 'scenes/userLogic'

import type { supportLogicType } from './supportLogicType'
import { forms } from 'kea-forms'
import { UserType } from '~/types'
import { lemonToast } from 'lib/lemon-ui/lemonToast'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { captureException } from '@sentry/react'

function getSessionReplayLink(): string {
    const LOOK_BACK = 30
    const recordingStartTime = Math.max(
        Math.floor((new Date().getTime() - (posthog?.sessionManager?._sessionStartTimestamp || 0)) / 1000) - LOOK_BACK,
        0
    )
    const link = `https://app.posthog.com/recordings/${posthog?.sessionRecording?.sessionId}?t=${recordingStartTime}`
    return `[Session replay](${link})`
}

function getDjangoAdminLink(user: UserType | null): string {
    if (!user) {
        return ''
    }
    const link = `${window.location.origin}/admin/posthog/user/?q=${user.email}`
    return `[Admin](${link}) (Organization: '${user.organization?.name}'; Project: ${user.team?.id}:'${user.team?.name}')`
}

function getSentryLinks(user: UserType | null): string {
    if (!user) {
        return ''
    }
    const cloud = window.location.origin == 'https://eu.posthog.com' ? 'EU' : 'US'
    const link = `http://go/sentry${cloud}/${user.email}`
    const pluginServer = `http://go/pluginServerSentry${cloud}/${user.team?.id}`
    return `[Sentry](${link}) | [Plugin Server Sentry](${pluginServer})`
}

export const TARGET_AREA_TO_NAME = {
    app_performance: 'App Performance',
    apps: 'Apps',
    login: 'Authentication (Login / Sign-up / Invites)',
    billing: 'Billing',
    cohorts: 'Cohorts',
    data_integrity: 'Data Integrity',
    data_management: 'Data Management',
    ingestion: 'Event Ingestion',
    experiments: 'Experiments',
    feature_flags: 'Feature Flags',
    analytics: 'Product Analytics (Insights, Dashboards, Annotations)',
    session_replay: 'Session Replay (Recordings)',
}
export const SUPPORT_KIND_TO_SUBJECT = {
    bug: 'Bug Report',
    feedback: 'Feedback',
    support: 'Support Ticket',
}
export type SupportTicketTargetArea = keyof typeof TARGET_AREA_TO_NAME
export type SupportTicketKind = keyof typeof SUPPORT_KIND_TO_SUBJECT

export const URL_PATH_TO_TARGET_AREA: Record<string, SupportTicketTargetArea> = {
    insights: 'analytics',
    recordings: 'session_replay',
    replay: 'session_replay',
    dashboard: 'analytics',
    feature_flags: 'feature_flags',
    experiments: 'experiments',
    'web-performance': 'session_replay',
    events: 'analytics',
    'data-management': 'data_management',
    cohorts: 'cohorts',
    annotations: 'analytics',
    persons: 'data_integrity',
    groups: 'data_integrity',
    app: 'apps',
    toolbar: 'analytics',
}

export function getURLPathToTargetArea(pathname: string): SupportTicketTargetArea | null {
    const first_part = pathname.split('/')[1]
    return URL_PATH_TO_TARGET_AREA[first_part] ?? null
}

export const supportLogic = kea<supportLogicType>([
    path(['lib', 'components', 'support', 'supportLogic']),
    connect(() => ({
        values: [userLogic, ['user']],
    })),
    actions(() => ({
        closeSupportForm: () => true,
        openSupportForm: (
            kind: SupportTicketKind | null = null,
            target_area: SupportTicketTargetArea | null = null
        ) => ({
            kind,
            target_area,
        }),
        submitZendeskTicket: (
            kind: SupportTicketKind | null,
            target_area: SupportTicketTargetArea | null,
            message: string
        ) => ({
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
                closeSupportForm: () => false,
            },
        ],
    })),
    forms(({ actions }) => ({
        sendSupportRequest: {
            defaults: {} as unknown as {
                kind: SupportTicketKind | null
                target_area: SupportTicketTargetArea | null
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
                actions.submitZendeskTicket(kind, target_area, message)
                actions.closeSupportForm()
                actions.resetSendSupportRequest()
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
        submitZendeskTicket: async ({ kind, target_area, message }) => {
            const name = userLogic.values.user?.first_name
            const email = userLogic.values.user?.email

            const zendesk_ticket_uuid = uuid()
            const subject =
                SUPPORT_KIND_TO_SUBJECT[kind ?? 'support'] +
                ': ' +
                (target_area ? TARGET_AREA_TO_NAME[target_area] : 'General') +
                ' (' +
                zendesk_ticket_uuid +
                ')'
            const payload = {
                request: {
                    requester: { name: name, email: email },
                    subject: subject,
                    comment: {
                        body:
                            message +
                            `\n\n-----` +
                            `\nKind: ${kind}` +
                            `\nTarget area: ${target_area}` +
                            `\nInternal links: [Event](http://go/ticketByUUID/${zendesk_ticket_uuid})` +
                            '\n' +
                            getSessionReplayLink() +
                            '\n' +
                            getDjangoAdminLink(userLogic.values.user) +
                            '\n' +
                            getSentryLinks(userLogic.values.user),
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
                    lemonToast.success(
                        "Got the message! If we have follow-up information for you, we'll reply via email."
                    )
                })
                .catch((err) => {
                    captureException(err)
                    console.log(err)
                    lemonToast.error(`There was an error sending the message.`)
                })
        },
    })),

    urlToAction(({ actions, values }) => ({
        '*': (_, _search, hashParams) => {
            if ('supportModal' in hashParams && !values.isSupportFormOpen) {
                const [kind, area] = (hashParams['supportModal'] || '').split(':')

                actions.openSupportForm(
                    Object.keys(SUPPORT_KIND_TO_SUBJECT).includes(kind) ? kind : null,
                    Object.keys(TARGET_AREA_TO_NAME).includes(area) ? area : null
                )
            }
        },
    })),
    actionToUrl(({ values }) => {
        const updateUrl = (): any => {
            const hashParams = router.values.hashParams
            hashParams['supportModal'] = `${values.sendSupportRequest.kind || ''}:${
                values.sendSupportRequest.target_area || ''
            }`
            return [router.values.location.pathname, router.values.searchParams, hashParams]
        }
        return {
            openSupportForm: () => updateUrl(),
            setSendSupportRequestValue: () => updateUrl(),
            closeSupportForm: () => {
                const hashParams = router.values.hashParams
                delete hashParams['supportModal']
                return [router.values.location.pathname, router.values.searchParams, hashParams]
            },
        }
    }),
])
