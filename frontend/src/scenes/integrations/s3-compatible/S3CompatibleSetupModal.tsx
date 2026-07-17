import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { S3CompatibleSetupModalLogicProps, s3CompatibleSetupModalLogic } from './s3CompatibleSetupModalLogic'

export const S3CompatibleSetupModal = (props: S3CompatibleSetupModalLogicProps): JSX.Element => {
    const { isS3CompatibleIntegrationSubmitting } = useValues(s3CompatibleSetupModalLogic(props))
    const { submitS3CompatibleIntegration } = useActions(s3CompatibleSetupModalLogic(props))

    return (
        <LemonModal
            isOpen={props.isOpen}
            title="Configure S3-compatible storage connection"
            description="Connect PostHog to any S3-compatible object storage (e.g. Cloudflare R2, DigitalOcean Spaces, Supabase). Credentials are stored encrypted and can be reused across exports."
            onClose={props.onComplete}
            footer={
                <>
                    <LemonButton type="secondary" onClick={() => props.onComplete()}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        loading={isS3CompatibleIntegrationSubmitting}
                        onClick={submitS3CompatibleIntegration}
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <Form logic={s3CompatibleSetupModalLogic} formKey="s3CompatibleIntegration" className="flex flex-col gap-4">
                <LemonField name="name" label="Name" info="A name to identify this connection across exports.">
                    <LemonInput placeholder="e.g. R2 data lake" />
                </LemonField>
                <LemonField
                    name="endpointUrl"
                    label="Endpoint URL"
                    info="The endpoint URL for your provider (e.g. Cloudflare R2, DigitalOcean Spaces, Supabase)."
                >
                    <LemonInput placeholder="e.g. https://<account-id>.r2.cloudflarestorage.com" />
                </LemonField>
                <LemonField name="awsAccessKeyId" label="Access Key ID">
                    <LemonInput placeholder="e.g. AKIAIOSFODNN7EXAMPLE" autoComplete="off" />
                </LemonField>
                <LemonField name="awsSecretAccessKey" label="Secret Access Key">
                    <LemonInput type="password" placeholder="e.g. secret-key" autoComplete="new-password" />
                </LemonField>
            </Form>
        </LemonModal>
    )
}
