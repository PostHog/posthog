import { lemonToast } from '@posthog/lemon-ui'
import { kea, path, listeners, selectors, connect, afterMount, actions } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { systemStatusLogic } from 'scenes/instance/SystemStatus/systemStatusLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'
import { IntegrationType } from '~/types'

import type { integrationsLogicType } from './integrationsLogicType'

// NOTE: Slack enforces HTTPS urls so to aid local dev we change to https so the redirect works.
// Just means we have to change it back to http once redirected.
export const getSlackRedirectUri = (): string =>
    `${window.location.origin.replace('http://', 'https://')}/integrations/slack/redirect`

// Modified version of https://app.slack.com/app-settings/TSS5W8YQZ/A03KWE2FJJ2/app-manifest to match current instance
export const getSlackAppManifest = (): any => ({
    display_information: {
        name: 'PostHog',
        description: 'Product Insights right where you need them',
        background_color: '#f54e00',
    },
    features: {
        bot_user: {
            display_name: 'PostHog',
            always_online: false,
        },
    },
    oauth_config: {
        redirect_urls: [getSlackRedirectUri()],
        scopes: {
            bot: ['channels:read', 'chat:write'],
        },
    },
    settings: {
        org_deploy_enabled: false,
        socket_mode_enabled: false,
        token_rotation_enabled: false,
    },
})

export const integrationsLogic = kea<integrationsLogicType>([
    path(['scenes', 'project', 'Settings', 'integrationsLogic']),
    connect({
        values: [preflightLogic, ['siteUrlMisconfigured', 'preflight'], systemStatusLogic, ['instanceSettings']],
        actions: [systemStatusLogic, ['loadInstanceSettings']],
    }),

    actions({
        handleRedirect: (kind: string, searchParams: any) => ({ kind, searchParams }),
    }),

    loaders(({}) => ({
        integrations: [
            null as IntegrationType[] | null,
            {
                loadIntegrations: async () => {
                    const res = await api.integrations.list()
                    return res.results
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        handleRedirect: async ({ kind, searchParams }) => {
            switch (kind) {
                case 'slack':
                    const { state, code } = searchParams

                    try {
                        await api.integrations.create({
                            kind: 'slack',
                            config: { state, code, redirect_uri: getSlackRedirectUri() },
                        })

                        actions.loadIntegrations()
                        lemonToast.success(`Integration successful.`)
                    } catch (e) {
                        lemonToast.error(`Something went wrong. Please try again.`)
                    } finally {
                        router.actions.replace(urls.projectSettings())
                    }

                    return
                default:
                    lemonToast.error(`Something went wrong.`)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadIntegrations()
        actions.loadInstanceSettings()
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
        addToSlackButtonUrl: [
            (s) => [s.instanceSettings],
            (instanceSettings) => {
                const clientId = instanceSettings.find((item) => item.key === 'SLACK_APP_CLIENT_ID')?.value

                return clientId
                    ? `https://slack.com/oauth/v2/authorize?client_id=${clientId}&scope=channels:read,chat:write&redirect_uri=${encodeURIComponent(
                          getSlackRedirectUri()
                      )}`
                    : null
            },
        ],
    }),
])
