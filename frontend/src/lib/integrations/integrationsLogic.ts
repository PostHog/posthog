import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

import { IntegrationType } from '~/types'

import type { integrationsLogicType } from './integrationsLogicType'

// NOTE: Slack enforces HTTPS urls so to aid local dev we change to https so the redirect works.
// Just means we have to change it back to http once redirected.
const getOauthRedirectURI = (kind: string, next: string = ''): string =>
    `${window.location.origin.replace('http://', 'https://')}/integrations/${kind}/callback${
        next ? '?next=' + encodeURIComponent(next) : ''
    }`

export const integrationsLogic = kea<integrationsLogicType>([
    path(['lib', 'integrations', 'integrationsLogic']),
    connect({
        values: [preflightLogic, ['siteUrlMisconfigured', 'preflight']],
    }),

    actions({
        handleOauthCallback: (kind: string, searchParams: any) => ({ kind, searchParams }),
        deleteIntegration: (id: number) => ({ id }),
    }),

    loaders(() => ({
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
        handleOauthCallback: async ({ kind, searchParams }) => {
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
                            config: { state, code, redirect_uri: getOauthRedirectURI('slack', next) },
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
        '/integrations/:kind/callback': ({ kind = '' }, searchParams) => {
            actions.handleOauthCallback(kind, searchParams)
        },
    })),
    selectors({
        slackIntegrations: [
            (s) => [s.integrations],
            (integrations) => {
                return integrations?.filter((x) => x.kind == 'slack')
            },
        ],

        addToSlackButtonUrl: [
            (s) => [s.preflight],
            (preflight) => {
                return (next: string = '') => {
                    const clientId = preflight?.slack_service?.client_id

                    return clientId
                        ? `https://slack.com/oauth/v2/authorize?client_id=${clientId}&scope=channels:read,groups:read,chat:write&redirect_uri=${encodeURIComponent(
                              getOauthRedirectURI('slack', next)
                          )}`
                        : null
                }
            },
        ],
    }),
])
