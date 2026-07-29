import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { RedshiftSetupModalLogicProps, redshiftSetupModalLogic } from './redshiftSetupModalLogic'

export const RedshiftSetupModal = (props: RedshiftSetupModalLogicProps): JSX.Element => {
    const { authMode, isRedshiftIntegrationSubmitting } = useValues(redshiftSetupModalLogic(props))
    const { setAuthMode, submitRedshiftIntegration } = useActions(redshiftSetupModalLogic(props))

    return (
        <LemonModal isOpen={props.isOpen} title="Configure Redshift connection" onClose={props.onComplete}>
            <Form logic={redshiftSetupModalLogic} props={props} formKey="redshiftIntegration">
                <div className="gap-4 flex flex-col">
                    <LemonField name="name" label="Name">
                        <LemonInput placeholder="Production Redshift" />
                    </LemonField>

                    <LemonField name="authentication_type" label="Authentication">
                        <LemonSelect
                            value={authMode}
                            onChange={(value) => setAuthMode(value as typeof authMode)}
                            options={[
                                { value: 'password', label: 'Password' },
                                { value: 'iam_role', label: 'IAM role' },
                            ]}
                        />
                    </LemonField>

                    {authMode === 'password' ? (
                        <>
                            <LemonField name="user" label="User">
                                <LemonInput placeholder="batch_exporter" />
                            </LemonField>

                            <LemonField name="password" label="Password">
                                <LemonInput type="password" autoComplete="new-password" />
                            </LemonField>
                        </>
                    ) : (
                        <>
                            <LemonField name="awsRoleArn" label="IAM role ARN">
                                <LemonInput placeholder="arn:aws:iam::123456789012:role/posthog-redshift" />
                            </LemonField>
                        </>
                    )}

                    <div className="flex justify-end">
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isRedshiftIntegrationSubmitting}
                            onClick={submitRedshiftIntegration}
                        >
                            Connect
                        </LemonButton>
                    </div>
                </div>
            </Form>
        </LemonModal>
    )
}
