import { actions, reducers, connect, listeners, kea, path, props } from 'kea'
import { forms } from 'kea-forms'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { IntegrationType } from '~/types'

import type { googleCloudServiceAccountSetupModalLogicType } from './googleCloudServiceAccountSetupModalLogicType'

export type ServiceAccountMode = 'impersonated' | 'key_file'

export interface GoogleCloudServiceAccountSetupModalLogicProps {
    isOpen: boolean
    integration?: IntegrationType | null
    onComplete: (integrationId?: number) => void
}

export const googleCloudServiceAccountSetupModalLogic = kea<googleCloudServiceAccountSetupModalLogicType>([
    path(['integrations', 'googleCloudServiceAccount', 'googleCloudServiceAccountSetupModalLogic']),
    props({} as GoogleCloudServiceAccountSetupModalLogicProps),
    connect(() => ({
        actions: [integrationsLogic, ['loadIntegrations']],
    })),
    actions({
        setServiceAccountMode: (mode: ServiceAccountMode) => ({ mode }),
    }),
    reducers({
        serviceAccountMode: [
            'impersonated' as ServiceAccountMode,
            {
                setServiceAccountMode: (_, { mode }) => mode,
            },
        ],
    }),
    forms(({ props, actions, values }) => ({
        googleCloudServiceAccountIntegration: {
            defaults: {
                projectId: '',
                serviceAccountEmail: '',
                jsonKeyFile: null,
                privateKey: null as string | null,
                privateKeyId: null as string | null,
                tokenUri: null as string | null,
            },
            errors: ({ projectId, serviceAccountEmail }) => ({
                projectId: projectId.trim() ? undefined : 'Project ID is required',
                serviceAccountEmail: serviceAccountEmail.trim() ? undefined : 'Service account email is required',
            }),
            submit: async () => {
                try {
                    const { projectId, serviceAccountEmail, privateKey, privateKeyId, tokenUri } =
                        values.googleCloudServiceAccountIntegration
                    const integration = await api.integrations.create({
                        kind: 'google-cloud-service-account',
                        config: {
                            project_id: projectId,
                            service_account_email: serviceAccountEmail,
                            ...(privateKey && {
                                private_key: privateKey,
                                private_key_id: privateKeyId,
                                token_uri: tokenUri,
                            }),
                        },
                    })
                    actions.loadIntegrations()
                    lemonToast.success('Google Cloud service account integration created successfully!')
                    props.onComplete(integration.id)
                } catch (error: any) {
                    lemonToast.error(error.detail || 'Failed to create Google Cloud service account integration')
                    throw error
                }
            },
        },
    })),
    listeners(({ values, actions }) => ({
        setServiceAccountMode: () => {
            actions.setGoogleCloudServiceAccountIntegrationValues({
                jsonKeyFile: null,
                projectId: '',
                serviceAccountEmail: '',
                privateKey: null,
                privateKeyId: null,
                tokenUri: null,
            })
        },
        setGoogleCloudServiceAccountIntegrationValue: async ({ name, value }) => {
            const fieldName = Array.isArray(name) ? name[0] : name
            if (fieldName === 'jsonKeyFile' && value) {
                try {
                    const loadedFile: string = await new Promise((resolve, reject) => {
                        const filereader = new FileReader()
                        filereader.onload = (e) => resolve(e.target?.result as string)
                        filereader.onerror = (e) => reject(e)
                        filereader.readAsText(value[0])
                    })
                    const loadedKeyFile = JSON.parse(loadedFile)
                    const { jsonKeyFile, ...remaining } = values.googleCloudServiceAccountIntegration
                    actions.setGoogleCloudServiceAccountIntegrationValues({
                        ...remaining,
                        projectId: loadedKeyFile.project_id ?? '',
                        serviceAccountEmail: loadedKeyFile.client_email ?? '',
                        privateKey: loadedKeyFile.private_key ?? null,
                        privateKeyId: loadedKeyFile.private_key_id ?? null,
                        tokenUri: loadedKeyFile.token_uri ?? null,
                    })
                } catch {
                    actions.setGoogleCloudServiceAccountIntegrationManualErrors({
                        jsonKeyFile: 'The JSON key file is not valid',
                    })
                }
            }
        },
    })),
])
