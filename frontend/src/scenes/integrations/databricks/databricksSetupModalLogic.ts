import { connect, kea, path, props } from 'kea'
import { forms } from 'kea-forms'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { IntegrationType } from '~/types'

import type { databricksSetupModalLogicType } from './databricksSetupModalLogicType'

export interface DatabricksSetupModalLogicProps {
    isOpen: boolean
    integration?: IntegrationType | null
    onComplete: (integrationId?: number) => void
}

export const databricksSetupModalLogic = kea<databricksSetupModalLogicType>([
    path(['integrations', 'databricks', 'databricksSetupModalLogic']),
    props({} as DatabricksSetupModalLogicProps),
    connect(() => ({
        actions: [integrationsLogic, ['loadIntegrations']],
    })),
    forms(({ props, actions, values }) => ({
        databricksIntegration: {
            defaults: {
                serverHostname: '',
                clientId: '',
                clientSecret: '',
            },
            errors: ({ serverHostname, clientId, clientSecret }) => ({
                serverHostname: serverHostname.trim() ? undefined : 'Server Hostname is required',
                clientId: clientId.trim() ? undefined : 'Client ID is required',
                clientSecret: clientSecret.trim() ? undefined : 'Client Secret is required',
            }),
            submit: async () => {
                try {
                    const integration = await api.integrations.create({
                        kind: 'databricks',
                        config: {
                            server_hostname: values.databricksIntegration.serverHostname,
                            client_id: values.databricksIntegration.clientId,
                            client_secret: values.databricksIntegration.clientSecret,
                        },
                    })
                    actions.loadIntegrations()
                    lemonToast.success('Databricks integration created successfully!')
                    props.onComplete(integration.id)
                } catch (error: any) {
                    lemonToast.error(error.detail || 'Failed to create Databricks integration')
                    throw error
                }
            },
        },
    })),
])
