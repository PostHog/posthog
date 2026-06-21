import { actions, afterMount, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { LemonDialog, lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'
import { ICONS } from 'lib/integrations/utils'

import { IntegrationKind, IntegrationType } from '~/types'

import type { organizationIntegrationsLogicType } from './organizationIntegrationsLogicType'

export const organizationIntegrationsLogic = kea<organizationIntegrationsLogicType>([
    path(['scenes', 'settings', 'organization', 'organizationIntegrationsLogic']),

    actions({
        deleteOrganizationIntegration: (id: IntegrationType['id']) => ({ id }),
    }),

    loaders(() => ({
        organizationIntegrations: [
            null as IntegrationType[] | null,
            {
                loadOrganizationIntegrations: async () => {
                    try {
                        const res = await api.organizationIntegrations.list()

                        return res.results.map((integration) => {
                            return {
                                ...integration,
                                icon_url: ICONS[integration.kind],
                            }
                        })
                    } catch (error) {
                        // Users without a current organization or membership get a by-design 404
                        // from `@current` org resolution — show an empty state rather than surfacing
                        // an uncaught exception to error tracking.
                        if (error instanceof ApiError && error.status === 404) {
                            return []
                        }
                        throw error
                    }
                },
            },
        ],
    })),

    selectors({
        vercelIntegrations: [
            (s) => [s.organizationIntegrations],
            (organizationIntegrations) => {
                return organizationIntegrations?.filter((x) => x.kind === 'vercel')
            },
        ],
        getOrganizationIntegrationsByKind: [
            (s) => [s.organizationIntegrations],
            (organizationIntegrations) => {
                return (kinds: IntegrationKind[]) =>
                    organizationIntegrations?.filter((i) => kinds.includes(i.kind)) || []
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        deleteOrganizationIntegration: ({ id }) => {
            const integration = values.organizationIntegrations?.find((x) => x.id === id)
            if (!integration) {
                return
            }

            LemonDialog.open({
                title: `Disconnect ${integration.kind} integration?`,
                description:
                    'This will remove the integration from your organization. PostHog resources configured to use this integration will stop working.',
                primaryButton: {
                    children: 'Yes, disconnect',
                    status: 'danger',
                    onClick: async () => {
                        try {
                            await api.organizationIntegrations.delete(id)
                            lemonToast.success('Integration disconnected.')
                            actions.loadOrganizationIntegrations()
                        } catch {
                            lemonToast.error('Failed to disconnect integration. Please try again.')
                        }
                    },
                },
                secondaryButton: {
                    children: 'Cancel',
                },
            })
        },
    })),

    afterMount(({ actions }) => {
        actions.loadOrganizationIntegrations()
    }),
])
