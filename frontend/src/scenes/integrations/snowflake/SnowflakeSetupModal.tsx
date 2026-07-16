import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonFileInput, LemonInput, LemonModal, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { SnowflakeSetupModalLogicProps, snowflakeSetupModalLogic } from './snowflakeSetupModalLogic'

export const SnowflakeSetupModal = (props: SnowflakeSetupModalLogicProps): JSX.Element => {
    const { isSnowflakeIntegrationSubmitting, snowflakeIntegration } = useValues(snowflakeSetupModalLogic(props))
    const { submitSnowflakeIntegration } = useActions(snowflakeSetupModalLogic(props))

    return (
        <LemonModal
            isOpen={props.isOpen}
            width={680}
            title="Configure Snowflake connection"
            description="Enter your Snowflake credentials to connect PostHog to your account. They are stored encrypted and can be reused across exports."
            onClose={props.onComplete}
            footer={
                <>
                    <LemonButton type="secondary" onClick={() => props.onComplete()}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        loading={isSnowflakeIntegrationSubmitting}
                        onClick={submitSnowflakeIntegration}
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <Form logic={snowflakeSetupModalLogic} formKey="snowflakeIntegration" className="flex flex-col gap-4">
                <LemonField name="name" label="Name" info="A name to identify this connection across exports.">
                    <LemonInput placeholder="e.g. Production Snowflake account" />
                </LemonField>
                <LemonField name="account" label="Account">
                    <LemonInput placeholder="my-account" autoComplete="off" />
                </LemonField>
                <LemonField name="user" label="User">
                    <LemonInput placeholder="my-user" autoComplete="off" />
                </LemonField>
                <LemonField name="authentication_type" label="Authentication type">
                    <LemonSelect
                        options={[
                            { value: 'keypair', label: 'Key pair' },
                            { value: 'password', label: 'Password' },
                        ]}
                    />
                </LemonField>
                {snowflakeIntegration.authentication_type === 'keypair' ? (
                    <>
                        <LemonField
                            name="private_key_file"
                            label="Private key file"
                            help="Upload the key file you generated, or paste its contents below."
                        >
                            <LemonFileInput accept=".p8,.pem,.key" multiple={false} />
                        </LemonField>
                        <LemonField name="private_key" label="Private key">
                            <LemonTextArea className="ph-ignore-input" placeholder="my-private-key" minRows={8} />
                        </LemonField>
                        <LemonField name="private_key_passphrase" label="Private key passphrase" showOptional>
                            <LemonInput type="password" placeholder="my-passphrase" autoComplete="new-password" />
                        </LemonField>
                    </>
                ) : (
                    <LemonField name="password" label="Password">
                        <LemonInput type="password" placeholder="my-password" autoComplete="new-password" />
                    </LemonField>
                )}
            </Form>
        </LemonModal>
    )
}
