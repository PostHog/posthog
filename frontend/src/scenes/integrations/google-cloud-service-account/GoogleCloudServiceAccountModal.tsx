import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonFileInput, LemonInput, LemonSegmentedButton, LemonModal } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import IconGoogleCloud from 'public/services/google-cloud.png'

import {
    GoogleCloudServiceAccountSetupModalLogicProps,
    googleCloudServiceAccountSetupModalLogic,
} from './googleCloudServiceAccountSetupModalLogic'

export const GoogleCloudServiceAccountModal = (props: GoogleCloudServiceAccountSetupModalLogicProps): JSX.Element => {
    const logic = googleCloudServiceAccountSetupModalLogic(props)
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
                                value: 'real',
                                label: 'Upload service account JSON key file (not recommended)',
                            },
                        ]}
                        fullWidth
                    />
                    {serviceAccountMode === 'real' ? (
                        <LemonField
                            name="jsonKeyFile"
                            label="Service account JSON key file"
                            help="The project ID and service account email will be extracted automatically."
                        >
                            <LemonFileInput accept=".json" multiple={false} />
                        </LemonField>
                    ) : (
                        <>
                            <LemonField name="projectId" label="Project ID">
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
