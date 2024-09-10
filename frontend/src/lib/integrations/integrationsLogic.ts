import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { fromParamsGivenUrl } from 'lib/utils'
import IconGoogleCloud from 'public/services/google-cloud.png'
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
    'gc-pubsub': IconGoogleCloud,
}

export const integrationsLogic = kea<integrationsLogicType>([
    path(['lib', 'integrations', 'integrationsLogic']),
    connect({
        values: [preflightLogic, ['siteUrlMisconfigured', 'preflight']],
    }),

    actions({
        handleOauthCallback: (kind: IntegrationKind, searchParams: any) => ({ kind, searchParams }),
        newGoogleCloudKey: (kind: string, key: File, callback?: (integration: IntegrationType) => void) => ({
            kind,
            key,
            callback,
        }),
        deleteIntegration: (id: number) => ({ id }),
    }),

    loaders(({ values }) => ({
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
                newGoogleCloudKey: async ({ kind, key, callback }) => {
                    try {
                        const formData = new FormData()
                        formData.append('kind', kind)
                        formData.append('key', key)
                        const response = await api.integrations.create(formData)
                        const responseWithIcon = { ...response, icon_url: ICONS[kind] ?? ICONS['gc-pubsub'] }

                        // run onChange after updating the integrations loader
                        window.setTimeout(() => callback?.(responseWithIcon), 0)

                        if (
                            values.integrations?.find(
                                (x) => x.kind === kind && x.display_name === response.display_name
                            )
                        ) {
                            lemonToast.success('Google Cloud key updated.')
                            return values.integrations.map((x) =>
                                x.kind === kind && x.display_name === response.display_name ? responseWithIcon : x
                            )
                        }
                        lemonToast.success('Google Cloud key created.')
                        return [...(values.integrations ?? []), responseWithIcon]
                    } catch (e) {
                        lemonToast.error('Failed to upload Google Cloud key.')
                        throw e
                    }
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
