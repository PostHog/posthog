import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonBanner, LemonButton, LemonInput, LemonModal, LemonTabs } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { AwsRoleRequirements } from 'scenes/integrations/components/AwsRoleRequirements'

import { AwsS3SetupModalLogicProps, awsS3SetupModalLogic } from './awsS3SetupModalLogic'

export const AwsS3SetupModal = (props: AwsS3SetupModalLogicProps): JSX.Element => {
    const logic = awsS3SetupModalLogic(props)
    const { authMode, isAwsS3IntegrationSubmitting } = useValues(logic)
    const { setAuthMode, submitAwsS3Integration } = useActions(logic)

    return (
        <LemonModal
            isOpen={props.isOpen}
            title="Configure AWS S3 connection"
            description="Connect PostHog to your S3 buckets. Connections can be reused across exports."
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
                <LemonField name="name" label="Name" info="A name to identify this connection across exports.">
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
                        <LemonField
                            name="awsRoleArn"
                            label="IAM role ARN"
                            info="The ARN of an IAM role in your AWS account that PostHog will assume to write export data."
                        >
                            <LemonInput
                                placeholder="e.g. arn:aws:iam::123456789012:role/posthog-batch-exports"
                                autoComplete="off"
                            />
                        </LemonField>
                        <AwsRoleRequirements
                            permissions={
                                <>
                                    Grant the role <code>s3:PutObject</code> and <code>s3:AbortMultipartUpload</code> on
                                    the destination bucket and prefix. If the bucket uses KMS encryption, also grant{' '}
                                    <code>kms:GenerateDataKey</code> and <code>kms:Decrypt</code> on the key.
                                </>
                            }
                        />
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
