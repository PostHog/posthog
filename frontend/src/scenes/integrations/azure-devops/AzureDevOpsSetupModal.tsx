import { useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal, Link } from '@posthog/lemon-ui'

import { ICONS } from 'lib/integrations/utils'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { AzureDevOpsSetupModalLogicProps, azureDevOpsSetupModalLogic } from './azureDevOpsSetupModalLogic'

export const AzureDevOpsSetupModal = (props: AzureDevOpsSetupModalLogicProps): JSX.Element => {
    const logic = azureDevOpsSetupModalLogic(props)
    const { isAzureDevOpsIntegrationSubmitting } = useValues(logic)

    return (
        <LemonModal
            isOpen={props.isOpen}
            title={
                <div className="flex items-center gap-2">
                    <img className="size-6" src={ICONS['azure-devops']} alt="" />
                    <span>Connect Azure DevOps</span>
                </div>
            }
            onClose={props.onComplete}
        >
            <Form logic={azureDevOpsSetupModalLogic} props={props} formKey="azureDevOpsIntegration">
                <div className="gap-4 flex flex-col">
                    <LemonField
                        name="organization"
                        label="Organization"
                        help="Your organization name, as it appears in dev.azure.com/your-organization. Pasting the full URL also works."
                    >
                        <LemonInput type="text" placeholder="your-organization" />
                    </LemonField>
                    <LemonField name="project" label="Project">
                        <LemonInput type="text" placeholder="Your project" />
                    </LemonField>
                    <LemonField
                        name="personalAccessToken"
                        label="Personal access token"
                        help={
                            <>
                                Create a token with Code read and write access in{' '}
                                <Link
                                    target="_blank"
                                    to="https://learn.microsoft.com/azure/devops/organizations/accounts/use-personal-access-tokens-to-authenticate"
                                >
                                    Azure DevOps
                                </Link>
                                .
                            </>
                        }
                    >
                        <LemonInput
                            type="password"
                            autoComplete="new-password"
                            placeholder="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
                        />
                    </LemonField>
                    <div className="flex justify-end">
                        <LemonButton type="primary" htmlType="submit" loading={isAzureDevOpsIntegrationSubmitting}>
                            Connect
                        </LemonButton>
                    </div>
                </div>
            </Form>
        </LemonModal>
    )
}
