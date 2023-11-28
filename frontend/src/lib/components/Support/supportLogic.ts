import { captureException } from '@sentry/react'
import * as Sentry from '@sentry/react'
import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/lemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { uuid } from 'lib/utils'
import posthog from 'posthog-js'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { Region, SidePanelTab, TeamType, UserType } from '~/types'

import type { supportLogicType } from './supportLogicType'
import { openSupportModal } from './SupportModal'

function getSessionReplayLink(): string {
    const link = posthog
        .get_session_replay_url({ withTimestamp: true, timestampLookBack: 30 })
        .replace(window.location.origin + '/replay/', 'http://go/session/')

    return `Session: ${link} (at ${window.location.href.replace(/&supportModal=.+($|&)?/, '$1')})`
}

function getDjangoAdminLink(
    user: UserType | null,
    cloudRegion: Region | null | undefined,
    currentTeamId: TeamType['id'] | null
): string {
    if (!user || !cloudRegion) {
        return ''
    }
    const link = `http://go/admin${cloudRegion}/${user.email}`
    return `Admin: ${link} (Organization: '${user.organization?.name}'; Project: ${currentTeamId}:'${user.team?.name}')`
}

function getSentryLink(user: UserType | null, cloudRegion: Region | null | undefined): string {
    if (!user || !cloudRegion) {
        return ''
    }
    const link = `http://go/sentry${cloudRegion}/${user.team?.id}`
    return `Sentry: ${link}`
}

const SUPPORT_TICKET_KIND_TO_TITLE: Record<SupportTicketKind, string> = {
    support: 'Ask a question',
    feedback: 'Give feedback',
    bug: 'Report a bug',
}

export const TARGET_AREA_TO_NAME = {
    app_performance: 'App Performance',
    apps: 'Apps',
    login: 'Authentication (Login / Sign-up / Invites)',
    billing: 'Billing',
    cohorts: 'Cohorts',
    data_integrity: 'Data Integrity',
    data_management: 'Data Management',
    data_warehouse: 'Data Warehouse',
    ingestion: 'Event Ingestion',
    experiments: 'Experiments',
    feature_flags: 'Feature Flags',
    analytics: 'Product Analytics (Insights, Dashboards, Annotations)',
    session_replay: 'Session Replay (Recordings)',
    toolbar: 'Toolbar & heatmaps',
    surveys: 'Surveys',
    web_analytics: 'Web Analytics',
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
    toolbar: 'session_replay',
    warehouse: 'data_warehouse',
    surveys: 'surveys',
    web: 'web_analytics',
}

export function getURLPathToTargetArea(pathname: string): SupportTicketTargetArea | null {
    const first_part = pathname.split('/')[1]
    return URL_PATH_TO_TARGET_AREA[first_part] ?? null
}

export type SupportFormLogicProps = {
    onClose?: () => void
}

export type SupportFormFields = {
    name: string
    email: string
    kind: SupportTicketKind
    target_area: SupportTicketTargetArea | null
    message: string
}

export const supportLogic = kea<supportLogicType>([
    props({} as SupportFormLogicProps),
    path(['lib', 'components', 'support', 'supportLogic']),
    connect(() => ({
        values: [
            userLogic,
            ['user'],
            preflightLogic,
            ['preflight'],
            featureFlagLogic,
            ['featureFlags'],
            sidePanelStateLogic,
            ['sidePanelAvailable'],
        ],
        actions: [sidePanelStateLogic, ['openSidePanel', 'setSidePanelOptions']],
    })),
    actions(() => ({
        closeSupportForm: true,
        openSupportForm: (values: Partial<SupportFormFields>) => values,
        submitZendeskTicket: (form: SupportFormFields) => form,
        updateUrlParams: true,
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
    forms(({ actions, values }) => ({
        sendSupportRequest: {
            defaults: {
                name: '',
                email: '',
                kind: 'support',
                target_area: null,
                message: '',
            } as SupportFormFields,
            errors: ({ name, email, message, kind, target_area }) => {
                return {
                    name: !values.user ? (!name ? 'Please enter your name' : '') : '',
                    email: !values.user ? (!email ? 'Please enter your email' : '') : '',
                    message: !message ? 'Please enter a message' : '',
                    kind: !kind ? 'Please choose' : undefined,
                    target_area: !target_area ? 'Please choose' : undefined,
                }
            },
            submit: async (formValues) => {
                formValues.name = values.user?.first_name ?? formValues.name ?? ''
                formValues.email = values.user?.email ?? formValues.email ?? ''
                actions.submitZendeskTicket(formValues)
                actions.closeSupportForm()
                actions.resetSendSupportRequest()
            },
        },
    })),
    selectors({
        title: [
            (s) => [s.sendSupportRequest ?? null],
            (sendSupportRequest) =>
                sendSupportRequest.kind
                    ? SUPPORT_TICKET_KIND_TO_TITLE[sendSupportRequest.kind]
                    : 'Leave a message with PostHog',
        ],
    }),
    listeners(({ actions, props, values }) => ({
        updateUrlParams: async () => {
            const panelOptions = [
                values.sendSupportRequest.kind ?? '',
                values.sendSupportRequest.target_area ?? '',
            ].join(':')

            if (panelOptions !== ':') {
                actions.setSidePanelOptions(panelOptions)
            }
        },
        openSupportForm: async ({ name, email, kind, target_area, message }) => {
            const area = target_area ?? getURLPathToTargetArea(window.location.pathname)
            kind = kind ?? 'support'
            actions.resetSendSupportRequest({
                name: name ?? '',
                email: email ?? '',
                kind,
                target_area: area,
                message: message ?? '',
            })

            if (values.sidePanelAvailable) {
                const panelOptions = [kind ?? '', area ?? ''].join(':')
                actions.openSidePanel(SidePanelTab.Support, panelOptions === ':' ? undefined : panelOptions)
            } else {
                openSupportModal()
            }

            actions.updateUrlParams()
        },
        submitZendeskTicket: async ({ name, email, kind, target_area, message }) => {
            const zendesk_ticket_uuid = uuid()
            const subject =
                SUPPORT_KIND_TO_SUBJECT[kind ?? 'support'] +
                ': ' +
                (target_area ? TARGET_AREA_TO_NAME[target_area] ?? `${target_area} (feature preview)` : 'General') +
                ' (' +
                zendesk_ticket_uuid +
                ')'
            const cloudRegion = preflightLogic.values.preflight?.region

            const payload = {
                request: {
                    requester: { name: name, email: email },
                    subject: subject,
                    comment: {
                        body: (
                            message +
                            `\n\n-----` +
                            `\nKind: ${kind}` +
                            `\nTarget area: ${target_area}` +
                            `\nReport event: http://go/ticketByUUID/${zendesk_ticket_uuid}` +
                            '\n' +
                            getSessionReplayLink() +
                            '\n' +
                            getDjangoAdminLink(userLogic.values.user, cloudRegion, teamLogic.values.currentTeamId) +
                            '\n' +
                            getSentryLink(userLogic.values.user, cloudRegion)
                        ).trim(),
                    },
                },
            }

            try {
                const response = await fetch('https://posthoghelp.zendesk.com/api/v2/requests.json', {
                    method: 'POST',
                    body: JSON.stringify(payload, undefined, 4),
                    headers: { 'Content-Type': 'application/json' },
                })
                if (!response.ok) {
                    const error = new Error(`There was an error creating the support ticket with zendesk.`)
                    captureException(error, {
                        extra: { response, payload },
                    })
                    lemonToast.error(`There was an error sending the message.`)
                    return
                }

                const json = await response.json()

                const zendesk_ticket_id = json.request.id
                const zendesk_ticket_link = `https://posthoghelp.zendesk.com/agent/tickets/${zendesk_ticket_id}`
                const properties = {
                    zendesk_ticket_uuid,
                    kind,
                    target_area,
                    message,
                    zendesk_ticket_id,
                    zendesk_ticket_link,
                }
                posthog.capture('support_ticket', properties)
                Sentry.captureMessage('User submitted Zendesk ticket', {
                    tags: {
                        zendesk_ticket_uuid,
                        zendesk_ticket_link,
                        support_request_kind: kind,
                        support_request_area: target_area,
                        team_id: teamLogic.values.currentTeamId,
                    },
                    extra: properties,
                    level: 'log',
                })
                lemonToast.success("Got the message! If we have follow-up information for you, we'll reply via email.")
            } catch (e) {
                captureException(e)
                lemonToast.error(`There was an error sending the message.`)
            }
        },

        closeSupportForm: () => {
            props.onClose?.()
        },

        setSendSupportRequestValue: () => {
            actions.updateUrlParams()
        },
    })),

    urlToAction(({ actions, values }) => ({
        '*': (_, _search, hashParams) => {
            if (values.isSupportFormOpen) {
                return
            }

            const [panel, ...panelOptions] = (hashParams['panel'] ?? '').split(':')

            if (panel === SidePanelTab.Support) {
                const [kind, area] = panelOptions

                actions.openSupportForm({
                    kind: Object.keys(SUPPORT_KIND_TO_SUBJECT).includes(kind) ? kind : null,
                    target_area: Object.keys(TARGET_AREA_TO_NAME).includes(area) ? area : null,
                })
                return
            }

            // Legacy supportModal param
            if ('supportModal' in hashParams) {
                const [kind, area] = (hashParams['supportModal'] || '').split(':')

                actions.openSupportForm({
                    kind: Object.keys(SUPPORT_KIND_TO_SUBJECT).includes(kind) ? kind : null,
                    target_area: Object.keys(TARGET_AREA_TO_NAME).includes(area) ? area : null,
                })
            }
        },
    })),
    actionToUrl(({ values }) => {
        return {
            closeSupportForm: () => {
                if (values.featureFlags[FEATURE_FLAGS.POSTHOG_3000]) {
                    return
                }

                const hashParams = router.values.hashParams
                delete hashParams['supportModal'] // legacy value
                delete hashParams['panel']

                return [router.values.location.pathname, router.values.searchParams, hashParams]
            },
        }
    }),
])
