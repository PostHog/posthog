import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { AwsS3SetupModalLogicProps, awsS3SetupModalLogic } from './awsS3SetupModalLogic'

export const AwsS3SetupModal = (props: AwsS3SetupModalLogicProps): JSX.Element => {
    const { isAwsS3IntegrationSubmitting } = useValues(awsS3SetupModalLogic(props))
    const { submitAwsS3Integration } = useActions(awsS3SetupModalLogic(props))

    return (
        <LemonModal
            isOpen={props.isOpen}
            title="Configure AWS S3 connection"
            description="Enter your AWS credentials to connect PostHog to your S3 buckets. They are stored encrypted and can be reused across exports."
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
                <LemonField name="awsAccessKeyId" label="AWS Access Key ID">
                    <LemonInput placeholder="e.g. AKIAIOSFODNN7EXAMPLE" autoComplete="off" />
                </LemonField>
                <LemonField name="awsSecretAccessKey" label="AWS Secret Access Key">
                    <LemonInput type="password" placeholder="e.g. secret-key" autoComplete="new-password" />
                </LemonField>
            </Form>
        </LemonModal>
    )
}
