import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonInput,
    LemonModal,
    LemonSelect,
    LemonTabs,
    lemonToast,
} from '@posthog/lemon-ui'

import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput/LemonFileInput'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect'
import { AwsRoleRequirements } from 'scenes/integrations/components/AwsRoleRequirements'

import { RedshiftSetupModalLogicProps, redshiftSetupModalLogic } from './redshiftSetupModalLogic'

export const RedshiftSetupModal = (props: RedshiftSetupModalLogicProps): JSX.Element => {
    const logic = redshiftSetupModalLogic(props)
    const { authMode, redshiftIntegration, isRedshiftIntegrationSubmitting } = useValues(logic)
    const { setAuthMode, submitRedshiftIntegration, setRedshiftIntegrationValue } = useActions(logic)

    return (
        <LemonModal
            isOpen={props.isOpen}
            width={680}
            title="Configure Redshift connection"
            description="Connect PostHog to your Redshift cluster. Connections can be reused across exports."
            onClose={() => props.onComplete()}
            footer={
                <>
                    <LemonButton type="secondary" onClick={() => props.onComplete()}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        loading={isRedshiftIntegrationSubmitting}
                        onClick={submitRedshiftIntegration}
                        data-attr="redshift-integration-save"
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={redshiftSetupModalLogic}
                props={props}
                formKey="redshiftIntegration"
                className="flex flex-col gap-4"
            >
                <LemonTabs
                    activeKey={authMode}
                    onChange={setAuthMode}
                    tabs={[
                        { key: 'role', label: 'IAM role' },
                        { key: 'access_key', label: 'Access keys' },
                        { key: 'password', label: 'Username and password' },
                    ]}
                />

                {authMode === 'password' ? (
                    <>
                        <LemonField name="host" label="Host">
                            <LemonInput placeholder="e.g. my-cluster.abc123.us-east-1.redshift.amazonaws.com" />
                        </LemonField>

                        <LemonField name="port" label="Port">
                            <LemonInput type="number" min="0" max="65535" placeholder="5439" />
                        </LemonField>

                        <LemonField name="user" label="User">
                            <LemonInput placeholder="e.g. posthog" autoComplete="off" />
                        </LemonField>

                        <LemonField name="password" label="Password">
                            <LemonInput type="password" autoComplete="new-password" />
                        </LemonField>

                        <LemonField
                            name="sslMode"
                            label="Verify server identity?"
                            info={
                                <>
                                    Verifies that the certificate presented by the cluster is signed by a trusted
                                    certificate authority, and optionally that its hostname matches the host you
                                    entered. This guards against man-in-the-middle attacks.
                                    <br />
                                    <br />
                                    The connection is always encrypted regardless of this setting, because PostHog
                                    requires TLS. These options only add verification of the server certificate.
                                </>
                            }
                        >
                            <LemonSelect
                                options={[
                                    { value: 'require', label: 'No' },
                                    { value: 'verify-ca', label: 'Verify certificate authority' },
                                    { value: 'verify-full', label: 'Verify certificate authority and server hostname' },
                                ]}
                            />
                        </LemonField>

                        {redshiftIntegration.sslMode !== 'require' && (
                            <>
                                <LemonField name="useSystemCa">
                                    {({ value, onChange }) => (
                                        <LemonCheckbox
                                            bordered
                                            checked={!!value}
                                            onChange={onChange}
                                            label="Use the system certificate authorities"
                                        />
                                    )}
                                </LemonField>

                                {!redshiftIntegration.useSystemCa && (
                                    <LemonField name="sslRootCert" label="Root certificate">
                                        {() => (
                                            <LemonFileInput
                                                accept=".crt,.pem,.cer,.ca-bundle"
                                                multiple={false}
                                                onChange={(files) => {
                                                    if (!files[0]) {
                                                        setRedshiftIntegrationValue('sslRootCert', '')
                                                        return
                                                    }
                                                    void files[0]
                                                        .text()
                                                        .then((text) =>
                                                            setRedshiftIntegrationValue('sslRootCert', text)
                                                        )
                                                        .catch(() => {
                                                            lemonToast.error('Failed to read the certificate file')
                                                            setRedshiftIntegrationValue('sslRootCert', '')
                                                        })
                                                }}
                                            />
                                        )}
                                    </LemonField>
                                )}
                            </>
                        )}
                    </>
                ) : (
                    <>
                        <LemonField name="name" label="Name" info="A name to identify this connection across exports.">
                            <LemonInput placeholder="e.g. Production cluster" />
                        </LemonField>

                        {authMode === 'role' ? (
                            <>
                                <LemonField
                                    name="awsRoleArn"
                                    label="IAM role ARN"
                                    info="The ARN of an IAM role in your AWS account that PostHog assumes to get temporary Redshift credentials."
                                >
                                    <LemonInput
                                        placeholder="e.g. arn:aws:iam::123456789012:role/posthog-batch-exports"
                                        autoComplete="off"
                                    />
                                </LemonField>
                                <AwsRoleRequirements
                                    permissions={
                                        <>
                                            Grant the role <code>redshift:GetClusterCredentials</code> on the cluster,
                                            the database and the database user. On Redshift Serverless, grant{' '}
                                            <code>redshift-serverless:GetCredentials</code> on the workgroup instead.
                                        </>
                                    }
                                />
                            </>
                        ) : (
                            <>
                                <LemonBanner type="warning">
                                    Access keys are long-lived credentials stored by PostHog (encrypted). Prefer letting
                                    PostHog assume an IAM role to avoid creating and storing long-lived credentials.
                                </LemonBanner>
                                <LemonField name="awsAccessKeyId" label="AWS Access Key ID">
                                    <LemonInput placeholder="e.g. AKIAIOSFODNN7EXAMPLE" autoComplete="off" />
                                </LemonField>
                                <LemonField name="awsSecretAccessKey" label="AWS Secret Access Key">
                                    <LemonInput
                                        type="password"
                                        placeholder="e.g. secret-key"
                                        autoComplete="new-password"
                                    />
                                </LemonField>
                            </>
                        )}

                        <LemonField
                            name="user"
                            label="User"
                            info="The Redshift user to connect as. PostHog requests temporary credentials for this user on every run, so there is no database password to store."
                        >
                            <LemonInput placeholder="e.g. posthog" autoComplete="off" />
                        </LemonField>

                        <LemonCollapse
                            panels={[
                                {
                                    key: 'advanced',
                                    header: 'Advanced options',
                                    content: (
                                        <div className="flex flex-col gap-4">
                                            <LemonField
                                                name="groups"
                                                label="Database groups"
                                                showOptional
                                                info="Groups the user joins for the duration of each run. Leave empty to keep the user's existing groups."
                                            >
                                                {({ value, onChange }) => (
                                                    <LemonInputSelect
                                                        mode="multiple"
                                                        allowCustomValues
                                                        options={[]}
                                                        value={value ?? []}
                                                        onChange={onChange}
                                                        placeholder="Enter a group name"
                                                    />
                                                )}
                                            </LemonField>

                                            <LemonField name="autoCreate">
                                                {({ value, onChange }) => (
                                                    <LemonCheckbox
                                                        bordered
                                                        checked={!!value}
                                                        onChange={onChange}
                                                        label="Create the user if it does not exist"
                                                    />
                                                )}
                                            </LemonField>

                                            <LemonField
                                                name="workgroupArn"
                                                label="Serverless workgroup ARN"
                                                showOptional
                                                info="Only needed for Redshift Serverless. Leave empty for a provisioned cluster."
                                            >
                                                <LemonInput
                                                    placeholder="e.g. arn:aws:redshift-serverless:us-east-1:123456789012:workgroup/my-workgroup"
                                                    autoComplete="off"
                                                />
                                            </LemonField>
                                        </div>
                                    ),
                                },
                            ]}
                        />
                    </>
                )}
            </Form>
        </LemonModal>
    )
}
