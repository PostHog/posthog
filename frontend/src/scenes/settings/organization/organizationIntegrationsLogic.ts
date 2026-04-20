import { afterMount, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { ICONS } from 'lib/integrations/utils'

import { IntegrationKind, IntegrationType } from '~/types'

import type { organizationIntegrationsLogicType } from './organizationIntegrationsLogicType'

export const organizationIntegrationsLogic = kea<organizationIntegrationsLogicType>([
    path(['scenes', 'settings', 'organization', 'organizationIntegrationsLogic']),

    loaders(() => ({
        organizationIntegrations: [
            null as IntegrationType[] | null,
            {
                loadOrganizationIntegrations: async () => {
                    const res = await api.organizationIntegrations.list()

                    return res.results.map((integration) => {
                        return {
                            ...integration,
                            icon_url: ICONS[integration.kind],
                        }
                    })
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

    afterMount(({ actions }) => {
        actions.loadOrganizationIntegrations()
    }),
])
