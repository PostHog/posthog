import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

import { IntegrationType, SlackChannelType } from '~/types'

import type { integrationsLogicType } from './integrationsLogicType'

// NOTE: Slack enforces HTTPS urls so to aid local dev we change to https so the redirect works.
// Just means we have to change it back to http once redirected.
export const getSlackRedirectUri = (next: string = ''): string =>
    `${window.location.origin.replace('http://', 'https://')}/integrations/slack/redirect${
        next ? '?next=' + encodeURIComponent(next) : ''
    }`

export const getSlackEventsUri = (): string =>
    `${window.location.origin.replace('http://', 'https://')}/api/integrations/slack/events`

// Modified version of https://app.slack.com/app-settings/TSS5W8YQZ/A03KWE2FJJ2/app-manifest to match current instance
export const getSlackAppManifest = (): any => ({
    display_information: {
        name: 'PostHog',
        description: 'Product Insights right where you need them',
        background_color: '#f54e00',
    },
    features: {
        app_home: {
            home_tab_enabled: false,
            messages_tab_enabled: false,
            messages_tab_read_only_enabled: true,
        },
        bot_user: {
            display_name: 'PostHog',
            always_online: false,
        },
        unfurl_domains: [window.location.hostname],
    },
    oauth_config: {
        redirect_urls: [getSlackRedirectUri()],
        scopes: {
            bot: ['channels:read', 'chat:write', 'groups:read', 'links:read', 'links:write'],
        },
    },
    settings: {
        event_subscriptions: {
            request_url: getSlackEventsUri(),
            bot_events: ['link_shared'],
        },
        org_deploy_enabled: false,
        socket_mode_enabled: false,
        token_rotation_enabled: false,
    },
})

export const integrationsLogic = kea<integrationsLogicType>([
    path(['scenes', 'project', 'Settings', 'integrationsLogic']),
    connect({
        values: [preflightLogic, ['siteUrlMisconfigured', 'preflight']],
    }),

    actions({
        handleRedirect: (kind: string, searchParams: any) => ({ kind, searchParams }),
        deleteIntegration: (id: number) => ({ id }),
    }),

    loaders(({ values }) => ({
        integrations: [
            null as IntegrationType[] | null,
            {
                loadIntegrations: async () => {
                    const res = await api.integrations.list()
                    return res.results
                },
            },
        ],

        slackChannels: [
            null as SlackChannelType[] | null,
            {
                loadSlackChannels: async () => {
                    if (!values.slackIntegration) {
                        return null
                    }

                    const res = await api.integrations.slackChannels(values.slackIntegration.id)
                    return res.channels
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        handleRedirect: async ({ kind, searchParams }) => {
            switch (kind) {
                case 'slack': {
                    const { state, code, error, next } = searchParams

                    const replaceUrl = next || urls.settings('project')

                    if (error) {
                        lemonToast.error(`Failed due to "${error}"`)
                        router.actions.replace(replaceUrl)
                        return
                    }

                    try {
                        await api.integrations.create({
                            kind: 'slack',
                            config: { state, code, redirect_uri: getSlackRedirectUri(next) },
                        })

                        actions.loadIntegrations()
                        lemonToast.success(`Integration successful.`)
                    } catch (e) {
                        lemonToast.error(`Something went wrong. Please try again.`)
                    } finally {
                        router.actions.replace(replaceUrl)
                    }

                    return
                }
                default:
                    lemonToast.error(`Something went wrong.`)
            }
        },

        deleteIntegration: async ({ id }) => {
            await api.integrations.delete(id)
            actions.loadIntegrations()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadIntegrations()
    }),

    urlToAction(({ actions }) => ({
        '/integrations/:kind/redirect': ({ kind = '' }, searchParams) => {
            actions.handleRedirect(kind, searchParams)
        },
    })),
    selectors({
        slackIntegration: [
            (s) => [s.integrations],
            (integrations) => {
                return integrations?.find((x) => x.kind == 'slack')
            },
        ],

        isMemberOfSlackChannel: [
            (s) => [s.slackChannels],
            (slackChannels) => {
                return (channel: string) => {
                    if (!slackChannels) {
                        return null
                    }

                    const [channelId] = channel.split('|')

                    return slackChannels.find((x) => x.id === channelId)?.is_member
                }
            },
        ],
        addToSlackButtonUrl: [
            (s) => [s.preflight],
            (preflight) => {
                return (next: string = '') => {
                    const clientId = preflight?.slack_service?.client_id

                    return clientId
                        ? `https://slack.com/oauth/v2/authorize?client_id=${clientId}&scope=channels:read,groups:read,chat:write&redirect_uri=${encodeURIComponent(
                              getSlackRedirectUri(next)
                          )}`
                        : null
                }
            },
        ],
    }),
])
