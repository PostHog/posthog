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

export const ANTHROPIC_WORKSPACE_LABEL_MAX_LENGTH = 100

function extractApiErrorMessage(error: unknown): string | null {
    if (!error || typeof error !== 'object') {
        return null
    }
    const err = error as Record<string, unknown>
    if (typeof err.detail === 'string') {
        return err.detail
    }
    // DRF field errors: {config: ["msg"]} or {config: {workspace_label: ["msg"]}}
    for (const key of Object.keys(err)) {
        const value = err[key]
        if (typeof value === 'string') {
            return value
        }
        if (Array.isArray(value) && value.length > 0 && typeof value[0] === 'string') {
            return value[0]
        }
        if (value && typeof value === 'object') {
            const nested = extractApiErrorMessage(value)
            if (nested) {
                return nested
            }
        }
    }
    return null
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
            errors: ({ apiKey, workspaceLabel }) => ({
                apiKey: apiKey.trim() ? undefined : 'API key is required',
                workspaceLabel:
                    workspaceLabel.trim().length > ANTHROPIC_WORKSPACE_LABEL_MAX_LENGTH
                        ? `Display name must be ${ANTHROPIC_WORKSPACE_LABEL_MAX_LENGTH} characters or fewer`
                        : undefined,
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
                    actions.resetAnthropicIntegration()
                    if (typeof integration?.id === 'number') {
                        props.onComplete(integration.id)
                    } else {
                        props.onComplete()
                    }
                } catch (error: unknown) {
                    const message = extractApiErrorMessage(error) ?? 'Failed to create Anthropic integration'
                    lemonToast.error(message)
                    throw error
                }
            },
        },
    })),
])
