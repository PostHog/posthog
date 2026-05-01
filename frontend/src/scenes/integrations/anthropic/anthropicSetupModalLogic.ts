import { connect, kea, path, props } from 'kea'
import { forms } from 'kea-forms'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { IntegrationType } from '~/types'

import type { anthropicSetupModalLogicType } from './anthropicSetupModalLogicType'

export interface AnthropicSetupModalLogicProps {
    isOpen: boolean
    integration?: IntegrationType | null
    onComplete: (integrationId?: number) => void
}

export const anthropicSetupModalLogic = kea<anthropicSetupModalLogicType>([
    path(['integrations', 'anthropic', 'anthropicSetupModalLogic']),
    props({} as AnthropicSetupModalLogicProps),
    connect(() => ({
        actions: [integrationsLogic, ['loadIntegrations']],
    })),
    forms(({ props, actions, values }) => ({
        anthropicIntegration: {
            defaults: {
                apiKey: '',
                workspaceLabel: '',
            },
            errors: ({ apiKey }) => ({
                apiKey: apiKey.trim() ? undefined : 'API key is required',
            }),
            submit: async () => {
                const config: Record<string, string> = { api_key: values.anthropicIntegration.apiKey.trim() }
                const label = values.anthropicIntegration.workspaceLabel.trim()
                if (label) {
                    config.workspace_label = label
                }
                try {
                    const integration = await api.integrations.create({ kind: 'anthropic', config })
                    actions.loadIntegrations()
                    lemonToast.success('Anthropic integration created successfully!')
                    props.onComplete(integration.id)
                } catch (error: any) {
                    lemonToast.error(error.detail || 'Failed to create Anthropic integration')
                    throw error
                }
            },
        },
    })),
])
