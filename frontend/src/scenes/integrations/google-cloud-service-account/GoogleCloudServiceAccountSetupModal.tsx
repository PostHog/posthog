import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonBanner, LemonTabs, LemonButton, Link, LemonFileInput, LemonInput, LemonModal } from '@posthog/lemon-ui'

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
                    <LemonTabs
                        activeKey={serviceAccountMode}
                        onChange={setServiceAccountMode}
                        tabs={[
                            {
                                key: 'impersonated',
                                label: 'Impersonate service account',
                            },
                            {
                                key: 'key_file',
                                label: 'Upload service account JSON key file',
                            },
                        ]}
                    />
                    {serviceAccountMode === 'key_file' ? (
                        <>
                            <LemonBanner type="warning">
                                A service account JSON key file contains long-lived credentials. It is preferable to let
                                PostHog impersonate your service account to avoid creating, exchanging, and storing
                                long-lived credentials.
                            </LemonBanner>
                            <LemonField
                                name="jsonKeyFile"
                                label="Service account JSON key file"
                                help="The project ID and service account information will be extracted automatically."
                            >
                                <LemonFileInput accept=".json" multiple={false} />
                            </LemonField>
                        </>
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

                            <div className="border border-border rounded p-4 bg-bg-light flex flex-col gap-3 text-sm">
                                <p className="font-semibold m-0">Requirements</p>
                                <div className="flex gap-3 items-start">
                                    <span className="bg-primary-highlight text-primary-alt rounded-full w-5 h-5 flex items-center justify-center text-xs font-semibold shrink-0 mt-0.5">
                                        1
                                    </span>
                                    <p className="m-0 text-secondary">
                                        Add <code>posthog:{currentOrganization?.id}</code> to your service account's
                                        description.
                                    </p>
                                </div>
                                <div className="flex gap-3 items-start">
                                    <span className="bg-primary-highlight text-primary-alt rounded-full w-5 h-5 flex items-center justify-center text-xs font-semibold shrink-0 mt-0.5">
                                        2
                                    </span>
                                    <p className="m-0 text-secondary">
                                        Assign PostHog's service account:{' '}
                                        <code>posthog-batch-exports@posthog-external.iam.gserviceaccount.com</code> as a
                                        principal with access to your service account with the role{' '}
                                        <code>roles/iam.serviceAccountTokenCreator</code> to allow impersonation, and
                                        any role containing <code>iam.serviceAccounts.get</code> permission to allow us
                                        to verify ownership.
                                    </p>
                                </div>
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
