import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { fromParamsGivenUrl } from 'lib/utils'
import IconHubspot from 'public/services/hubspot.png'
import IconSalesforce from 'public/services/salesforce.png'
import IconSlack from 'public/services/slack.png'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

import { IntegrationKind, IntegrationType } from '~/types'

import type { integrationsLogicType } from './integrationsLogicType'

const ICONS: Record<IntegrationKind, any> = {
    slack: IconSlack,
    salesforce: IconSalesforce,
    hubspot: IconHubspot,
}

export const integrationsLogic = kea<integrationsLogicType>([
    path(['lib', 'integrations', 'integrationsLogic']),
    connect({
        values: [preflightLogic, ['siteUrlMisconfigured', 'preflight']],
    }),

    actions({
        handleOauthCallback: (kind: IntegrationKind, searchParams: any) => ({ kind, searchParams }),
        deleteIntegration: (id: number) => ({ id }),
    }),

    loaders(() => ({
        integrations: [
            null as IntegrationType[] | null,
            {
                loadIntegrations: async () => {
                    const res = await api.integrations.list()

                    // Simple modifier here to add icons and names - we can move this to the backend at some point

                    return res.results.map((integration) => {
                        return {
                            ...integration,
                            // TODO: Make the icons endpoint independent of hog functions
                            icon_url: ICONS[integration.kind],
                        }
                    })
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        handleOauthCallback: async ({ kind, searchParams }) => {
            const { state, code, error } = searchParams
            const { next } = fromParamsGivenUrl(state)
            let replaceUrl: string = next || urls.settings('project-integrations')

            if (error) {
                lemonToast.error(`Failed due to "${error}"`)
                router.actions.replace(replaceUrl)
                return
            }

            try {
                const integration = await api.integrations.create({
                    kind,
                    config: { state, code },
                })

                // Add the integration ID to the replaceUrl so that the landing page can use it
                replaceUrl += `${replaceUrl.includes('?') ? '&' : '?'}integration_id=${integration.id}`

                actions.loadIntegrations()
                lemonToast.success(`Integration successful.`)
            } catch (e) {
                lemonToast.error(`Something went wrong. Please try again.`)
            } finally {
                router.actions.replace(replaceUrl)
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
            actions.handleOauthCallback(kind as IntegrationKind, searchParams)
        },
    })),
    selectors({
        slackIntegrations: [
            (s) => [s.integrations],
            (integrations) => {
                return integrations?.filter((x) => x.kind == 'slack')
            },
        ],

        slackAvailable: [
            (s) => [s.preflight],
            (preflight) => {
                // TODO: Change this to be based on preflight or something
                return preflight?.slack_service?.available
            },
        ],
    }),
])
