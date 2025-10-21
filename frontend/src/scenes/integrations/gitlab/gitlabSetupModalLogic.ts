import { connect, kea, path, props } from 'kea'
import { forms } from 'kea-forms'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { IntegrationType } from '~/types'

import type { gitlabSetupModalLogicType } from './gitlabSetupModalLogicType'

export interface gitlabSetupModalLogicProps {
    isOpen: boolean
    integration?: IntegrationType | null
    onComplete: (integrationId?: number) => void
}

export interface gitlabFormType {
    serverHostname: string
    clientId: string
    clientSecret: string
}

export const gitlabSetupModalLogic = kea<gitlabSetupModalLogicType>([
    path(['integrations', 'gitlab', 'gitlabSetupModalLogic']),
    props({} as gitlabSetupModalLogicProps),
    connect(() => ({
        values: [integrationsLogic, ['integrations', 'integrationsLoading']],
        actions: [integrationsLogic, ['loadIntegrations']],
    })),
    forms(({ props, actions, values }) => ({
        gitlabIntegration: {
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
                        kind: 'gitlab',
                        config: {
                            server_hostname: values.gitlabIntegration.serverHostname,
                            client_id: values.gitlabIntegration.clientId,
                            client_secret: values.gitlabIntegration.clientSecret,
                        },
                    })
                    actions.loadIntegrations()
                    lemonToast.success('GitLab integration created successfully!')
                    props.onComplete(integration.id)
                } catch (error: any) {
                    lemonToast.error(error.detail || 'Failed to create GitLab integration')
                    throw error
                }
            },
        },
    })),
])
