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

export const GoogleCloudServiceAccountModal = (props: GoogleCloudServiceAccountSetupModalLogicProps): JSX.Element => {
    const logic = googleCloudServiceAccountSetupModalLogic(props)
    const { currentOrganization } = useValues(organizationLogic)
    const { serviceAccountMode, isGoogleCloudServiceAccountIntegrationSubmitting } = useValues(logic)
    const { setServiceAccountMode, submitGoogleCloudServiceAccountIntegration } = useActions(logic)

    return (
        <LemonModal
            isOpen={props.isOpen}
            title={
                <div className="flex items-center gap-2">
                    <IconGoogleCloud />
                    <span>Configure Google Cloud ServiceAccount</span>
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
                            <p className="text-sm text-primary">
                                PostHog will impersonate the service account you configure here with one of our own. You
                                must grant the PostHog service account the following permissions:
                                <ul>
                                    <li>
                                        <code>roles/iam.serviceAccountTokenCreator</code>: To allow impersonating.
                                    </li>
                                    <li>
                                        <code>iam.serviceAccounts.get</code>: To allow checking service account
                                        ownership.
                                    </li>
                                </ul>
                            </p>

                            <p className="text-sm text-warning">
                                In order to identify you as the owner of this service account, you must include{' '}
                                <code>posthog:{currentOrganization}</code> as part of the service account description.
                            </p>

                            <LemonField
                                name="projectId"
                                label="Project ID"
                                help={
                                    <Link target="_blank" to="https://support.google.com/googleapi/answer/7014113">
                                        {' '}
                                        Find your Project ID{' '}
                                    </Link>
                                }
                            >
                                <LemonInput placeholder="my-gcp-project" />
                            </LemonField>

                            <LemonField name="serviceAccountEmail" label="Service account email">
                                <LemonInput placeholder="my-sa@my-gcp-project.iam.gserviceaccount.com" />
                            </LemonField>
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
