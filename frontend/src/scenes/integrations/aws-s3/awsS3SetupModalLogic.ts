import { connect, kea, path, props } from 'kea'
import { forms } from 'kea-forms'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { IntegrationType } from '~/types'

import type { awsS3SetupModalLogicType } from './awsS3SetupModalLogicType'

export interface AwsS3SetupModalLogicProps {
    isOpen: boolean
    integration?: IntegrationType | null
    onComplete: (integrationId?: number) => void
}

export const awsS3SetupModalLogic = kea<awsS3SetupModalLogicType>([
    path(['integrations', 'aws-s3', 'awsS3SetupModalLogic']),
    props({} as AwsS3SetupModalLogicProps),
    connect(() => ({
        actions: [integrationsLogic, ['loadIntegrations']],
    })),
    forms(({ props, actions, values }) => ({
        awsS3Integration: {
            defaults: {
                name: '',
                awsAccessKeyId: '',
                awsSecretAccessKey: '',
            },
            errors: ({ name, awsAccessKeyId, awsSecretAccessKey }) => ({
                name: name.trim() ? undefined : 'Name is required',
                awsAccessKeyId: awsAccessKeyId.trim() ? undefined : 'Access Key ID is required',
                awsSecretAccessKey: awsSecretAccessKey.trim() ? undefined : 'Secret Access Key is required',
            }),
            submit: async () => {
                try {
                    const integration = await api.integrations.create({
                        kind: 'aws-s3',
                        config: {
                            name: values.awsS3Integration.name,
                            aws_access_key_id: values.awsS3Integration.awsAccessKeyId,
                            aws_secret_access_key: values.awsS3Integration.awsSecretAccessKey,
                        },
                    })
                    actions.loadIntegrations()
                    lemonToast.success('AWS S3 connection created successfully!')
                    props.onComplete(integration.id)
                } catch (error: any) {
                    lemonToast.error(error.detail || 'Failed to create AWS S3 connection')
                    throw error
                }
            },
        },
    })),
])
