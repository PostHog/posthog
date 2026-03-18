import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, Link, LemonFileInput, LemonInput, LemonSegmentedButton, LemonModal } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { organizationLogic } from 'scenes/organizationLogic'

import IconGoogleCloud from 'public/services/google-cloud.png'

import {
    GoogleCloudServiceAccountSetupModalLogicProps,
    googleCloudServiceAccountSetupModalLogic,
} from './googleCloudServiceAccountSetupModalLogic'

export const GoogleCloudServiceAccountSetupModal = (
    props: GoogleCloudServiceAccountSetupModalLogicProps
): JSX.Element => {
    const logic = googleCloudServiceAccountSetupModalLogic(props)
    const { currentOrganization } = useValues(organizationLogic)
    const { serviceAccountMode, isGoogleCloudServiceAccountIntegrationSubmitting } = useValues(logic)
    const { setServiceAccountMode, submitGoogleCloudServiceAccountIntegration } = useActions(logic)

    return (
        <LemonModal
            isOpen={props.isOpen}
            title={
                <div className="flex items-center gap-2">
                    <img src={IconGoogleCloud} alt="Google Cloud" className="w-6 h-6" />
                    <span>Configure Google Cloud service account</span>
                </div>
            }
            onClose={props.onComplete}
        >
            <Form
                logic={googleCloudServiceAccountSetupModalLogic}
                props={props}
                formKey="googleCloudServiceAccountIntegration"
            >
                <div className="gap-4 flex flex-col">
                    <LemonSegmentedButton
                        value={serviceAccountMode}
                        onChange={setServiceAccountMode}
                        options={[
                            {
                                value: 'impersonated',
                                label: 'Impersonate service account',
                            },
                            {
                                value: 'key_file',
                                label: 'Upload service account JSON key file (not recommended)',
                            },
                        ]}
                        fullWidth
                    />
                    {serviceAccountMode === 'key_file' ? (
                        <LemonField
                            name="jsonKeyFile"
                            label="Service account JSON key file"
                            help="The project ID and service account information will be extracted automatically."
                        >
                            <LemonFileInput accept=".json" multiple={false} />
                        </LemonField>
                    ) : (
                        <>
                            <LemonField
                                name="projectId"
                                label="Project ID"
                                help={
                                    <Link target="_blank" to="https://support.google.com/googleapi/answer/7014113">
                                        {' '}
                                        How do I find my Google Cloud Project ID?{' '}
                                    </Link>
                                }
                            >
                                <LemonInput placeholder="my-project" />
                            </LemonField>

                            <LemonField name="serviceAccountEmail" label="Service account email">
                                <LemonInput placeholder="service-account@my-google-cloud-project.iam.gserviceaccount.com" />
                            </LemonField>

                            <div className="text-sm text-primary">
                                <p>
                                    PostHog will impersonate this service account with one of our own:{' '}
                                    <code>posthog-batch-exports@posthog-external.iam.gserviceaccount.com</code>. You
                                    must grant our service account the <code>roles/iam.serviceAccountTokenCreator</code>{' '}
                                    role to allow impersonation.
                                </p>
                                <p>
                                    In order to identify you as the owner of this service account, you must include{' '}
                                    <code>posthog:{currentOrganization?.id}</code> as part of the service account's{' '}
                                    description, and grant our service account the <code>iam.serviceAccounts.get</code>{' '}
                                    permission to allow us to check it.
                                </p>
                            </div>
                        </>
                    )}

                    <div className="flex justify-end">
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isGoogleCloudServiceAccountIntegrationSubmitting}
                            onClick={submitGoogleCloudServiceAccountIntegration}
                        >
                            Connect
                        </LemonButton>
                    </div>
                </div>
            </Form>
        </LemonModal>
    )
}
