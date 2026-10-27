import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonBanner, LemonButton, LemonInput, LemonModal, LemonTabs } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { AwsRoleRequirements } from 'scenes/integrations/components/AwsRoleRequirements'

import { AwsKinesisSetupModalLogicProps, awsKinesisSetupModalLogic } from './awsKinesisSetupModalLogic'

export const AwsKinesisSetupModal = (props: AwsKinesisSetupModalLogicProps): JSX.Element => {
    const logic = awsKinesisSetupModalLogic(props)
    const { authMode, isAwsKinesisIntegrationSubmitting } = useValues(logic)
    const { setAuthMode, submitAwsKinesisIntegration } = useActions(logic)

    return (
        <LemonModal
            isOpen={props.isOpen}
            title="Configure AWS Kinesis connection"
            description="Connect PostHog to your Kinesis streams. Connections can be reused across destinations."
            onClose={props.onComplete}
            footer={
                <>
                    <LemonButton type="secondary" onClick={() => props.onComplete()}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        loading={isAwsKinesisIntegrationSubmitting}
                        onClick={submitAwsKinesisIntegration}
                        data-attr="aws-kinesis-connection-save"
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <Form logic={awsKinesisSetupModalLogic} formKey="awsKinesisIntegration" className="flex flex-col gap-4">
                <LemonField name="name" label="Name" info="A name to identify this connection across destinations.">
                    <LemonInput placeholder="e.g. Production event stream" />
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
                            info="The ARN of an IAM role in your AWS account that PostHog will assume to put records on your streams."
                        >
                            <LemonInput
                                placeholder="e.g. arn:aws:iam::123456789012:role/posthog-kinesis"
                                autoComplete="off"
                            />
                        </LemonField>
                        <AwsRoleRequirements
                            posthogRole="cdp-destinations"
                            permissions={
                                <>
                                    Grant the role <code>kinesis:PutRecord</code> and <code>kinesis:PutRecords</code> on
                                    the destination streams. If a stream uses a customer managed KMS key, also grant{' '}
                                    <code>kms:GenerateDataKey</code> on the key.
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
