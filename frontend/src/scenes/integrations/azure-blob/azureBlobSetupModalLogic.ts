import { connect, kea, path, props } from 'kea'
import { forms } from 'kea-forms'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { IntegrationType } from '~/types'

import type { azureBlobSetupModalLogicType } from './azureBlobSetupModalLogicType'

export interface AzureBlobSetupModalLogicProps {
    isOpen: boolean
    integration?: IntegrationType | null
    onComplete: (integrationId?: number) => void
}

export const azureBlobSetupModalLogic = kea<azureBlobSetupModalLogicType>([
    path(['integrations', 'azure-blob', 'azureBlobSetupModalLogic']),
    props({} as AzureBlobSetupModalLogicProps),
    connect(() => ({
        actions: [integrationsLogic, ['loadIntegrations']],
    })),
    forms(({ props, actions, values }) => ({
        azureBlobIntegration: {
            defaults: {
                connectionString: '',
            },
            errors: ({ connectionString }) => ({
                connectionString: !connectionString.trim()
                    ? 'Connection string is required'
                    : !connectionString.includes('AccountName=')
                      ? 'Connection string must contain AccountName'
                      : undefined,
            }),
            submit: async () => {
                try {
                    const integration = await api.integrations.create({
                        kind: 'azure-blob',
                        config: {
                            connection_string: values.azureBlobIntegration.connectionString,
                        },
                    })
                    actions.loadIntegrations()
                    lemonToast.success('Azure Blob Storage connection created successfully!')
                    props.onComplete(integration.id)
                } catch (error: any) {
                    lemonToast.error(error.detail || 'Failed to create Azure Blob Storage connection')
                    throw error
                }
            },
        },
    })),
])
