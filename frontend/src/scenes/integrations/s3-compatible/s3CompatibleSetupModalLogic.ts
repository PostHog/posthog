import { connect, kea, path, props } from 'kea'
import { forms } from 'kea-forms'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { IntegrationType } from '~/types'

import type { s3CompatibleSetupModalLogicType } from './s3CompatibleSetupModalLogicType'

export interface S3CompatibleSetupModalLogicProps {
    isOpen: boolean
    integration?: IntegrationType | null
    onComplete: (integrationId?: number) => void
}

export const s3CompatibleSetupModalLogic = kea<s3CompatibleSetupModalLogicType>([
    path(['integrations', 's3-compatible', 's3CompatibleSetupModalLogic']),
    props({} as S3CompatibleSetupModalLogicProps),
    connect(() => ({
        actions: [integrationsLogic, ['loadIntegrations']],
    })),
    forms(({ props, actions, values }) => ({
        s3CompatibleIntegration: {
            defaults: {
                name: '',
                endpointUrl: '',
                awsAccessKeyId: '',
                awsSecretAccessKey: '',
            },
            errors: ({ name, endpointUrl, awsAccessKeyId, awsSecretAccessKey }) => ({
                name: name.trim() ? undefined : 'Name is required',
                endpointUrl: endpointUrl.trim() ? undefined : 'Endpoint URL is required',
                awsAccessKeyId: awsAccessKeyId.trim() ? undefined : 'Access Key ID is required',
                awsSecretAccessKey: awsSecretAccessKey.trim() ? undefined : 'Secret Access Key is required',
            }),
            submit: async () => {
                try {
                    const integration = await api.integrations.create({
                        kind: 's3-compatible',
                        config: {
                            name: values.s3CompatibleIntegration.name,
                            endpoint_url: values.s3CompatibleIntegration.endpointUrl,
                            aws_access_key_id: values.s3CompatibleIntegration.awsAccessKeyId,
                            aws_secret_access_key: values.s3CompatibleIntegration.awsSecretAccessKey,
                        },
                    })
                    actions.loadIntegrations()
                    lemonToast.success('S3-compatible storage connection created successfully!')
                    props.onComplete(integration.id)
                } catch (error: any) {
                    lemonToast.error(error.detail || 'Failed to create S3-compatible storage connection')
                    throw error
                }
            },
        },
    })),
])
