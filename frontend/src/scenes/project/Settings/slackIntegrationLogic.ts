import { kea, path, listeners, selectors, connect, afterMount } from 'kea'
import { loaders } from 'kea-loaders'
import { systemStatusLogic } from 'scenes/instance/SystemStatus/systemStatusLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import type { slackIntegrationLogicType } from './slackIntegrationLogicType'

interface IntegrationsType {
    id: string
}

// NOTE: Slack enforces HTTPS urls so to aid local dev we change to https so the redirect works.
// Just means we have to change it back to http once redirected.
export const getSlackRedirectUri = (): string =>
    `${window.location.origin.replace('http://', 'https://')}/api/integrations/slack/complete`

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

export const slackIntegrationLogic = kea<slackIntegrationLogicType>([
    path(['scenes', 'project', 'Settings', 'slackIntegrationLogic']),
    connect({
        values: [preflightLogic, ['siteUrlMisconfigured', 'preflight'], systemStatusLogic, ['instanceSettings']],
        actions: [systemStatusLogic, ['loadInstanceSettings']],
    }),

    loaders(({}) => ({
        integrations: [
            null as IntegrationsType[] | null,
            {
                loadIntegrations: async () => {
                    return []
                },
            },
        ],
    })),
    listeners(() => ({})),
    afterMount(({ actions }) => {
        actions.loadIntegrations()
        actions.loadInstanceSettings()
    }),
    selectors({
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
