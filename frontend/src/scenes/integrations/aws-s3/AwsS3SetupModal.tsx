import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonBanner, LemonButton, LemonInput, LemonModal, LemonTabs } from '@posthog/lemon-ui'

import { IntegrationSetupPurpose } from 'lib/components/CyclotronJob/integrations/integrationSetupRegistry'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { AwsRoleRequirements } from 'scenes/integrations/components/AwsRoleRequirements'

import { AwsS3SetupModalLogicProps, awsS3SetupModalLogic } from './awsS3SetupModalLogic'

type RoleCopy = {
    description: string
    nameInfo: string
    roleArnInfo: string
    roleArnPlaceholder: string
    jobs: string
    permissions: JSX.Element
}

const ROLE_COPY: Record<IntegrationSetupPurpose, RoleCopy> = {
    export: {
        description: 'Connect PostHog to your S3 buckets. Connections can be reused across exports.',
        nameInfo: 'A name to identify this connection across exports.',
        roleArnInfo: 'The ARN of an IAM role in your AWS account that PostHog will assume to write export data.',
        roleArnPlaceholder: 'e.g. arn:aws:iam::123456789012:role/posthog-batch-exports',
        jobs: 'exports',
        permissions: (
            <>
                Grant the role <code>s3:PutObject</code> and <code>s3:AbortMultipartUpload</code> on the destination
                bucket and prefix. If the bucket uses KMS encryption, also grant <code>kms:GenerateDataKey</code> and{' '}
                <code>kms:Decrypt</code> on the key.
            </>
        ),
    },
    import: {
        description: 'Connect PostHog to your AWS account. Connections can be reused across sources.',
        nameInfo: 'A name to identify this connection across sources.',
        roleArnInfo: 'The ARN of an IAM role in your AWS account that PostHog will assume to read your data.',
        roleArnPlaceholder: 'e.g. arn:aws:iam::123456789012:role/posthog-data-warehouse',
        jobs: 'syncs',
        permissions: (
            <>
                Grant the role the read permissions listed in the source's setup instructions. PostHog only reads, so
                the role needs no write access.
            </>
        ),
    },
}

export type AwsS3SetupModalProps = AwsS3SetupModalLogicProps & {
    purpose?: IntegrationSetupPurpose
}

export const AwsS3SetupModal = ({ purpose = 'export', ...props }: AwsS3SetupModalProps): JSX.Element => {
    const copy = ROLE_COPY[purpose]
    const logic = awsS3SetupModalLogic(props)
    const { authMode, isAwsS3IntegrationSubmitting } = useValues(logic)
    const { setAuthMode, submitAwsS3Integration } = useActions(logic)

    return (
        <LemonModal
            isOpen={props.isOpen}
            title="Configure AWS S3 connection"
            description={copy.description}
            onClose={props.onComplete}
            footer={
                <>
                    <LemonButton type="secondary" onClick={() => props.onComplete()}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" loading={isAwsS3IntegrationSubmitting} onClick={submitAwsS3Integration}>
                        Save
                    </LemonButton>
                </>
            }
        >
            <Form logic={awsS3SetupModalLogic} formKey="awsS3Integration" className="flex flex-col gap-4">
                <LemonField name="name" label="Name" info={copy.nameInfo}>
                    <LemonInput placeholder="e.g. Production data lake" />
                </LemonField>
                <LemonTabs
                    activeKey={authMode}
                    onChange={setAuthMode}
                    tabs={[
                        {
                            key: 'role',
                            label: 'Assume IAM role',
                        },
                        {
                            key: 'access_key',
                            label: 'Access keys',
                        },
                    ]}
                />
                {authMode === 'role' ? (
                    <>
                        <LemonField name="awsRoleArn" label="IAM role ARN" info={copy.roleArnInfo}>
                            <LemonInput placeholder={copy.roleArnPlaceholder} autoComplete="off" />
                        </LemonField>
                        <AwsRoleRequirements permissions={copy.permissions} jobs={copy.jobs} />
                    </>
                ) : (
                    <>
                        <LemonBanner type="warning">
                            Access keys are long-lived credentials stored by PostHog (encrypted). Prefer letting PostHog
                            assume an IAM role to avoid creating and storing long-lived credentials.
                        </LemonBanner>
                        <LemonField name="awsAccessKeyId" label="AWS Access Key ID">
                            <LemonInput placeholder="e.g. AKIAIOSFODNN7EXAMPLE" autoComplete="off" />
                        </LemonField>
                        <LemonField name="awsSecretAccessKey" label="AWS Secret Access Key">
                            <LemonInput type="password" placeholder="e.g. secret-key" autoComplete="new-password" />
                        </LemonField>
                    </>
                )}
            </Form>
        </LemonModal>
    )
}
