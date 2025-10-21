import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { IconDatabricks } from 'lib/lemon-ui/icons'

import { GitLabSetupModalLogicProps, gitlabSetupModalLogic } from './databricksSetupModalLogic'

export const GitLabSetupModal = (props: GitLabSetupModalLogicProps): JSX.Element => {
    const { isGitLabIntegrationSubmitting } = useValues(gitlabSetupModalLogic(props))
    const { submitGitLabIntegration } = useActions(gitlabSetupModalLogic(props))

    return (
        <LemonModal
            isOpen={props.isOpen}
            title={
                <div className="flex items-center gap-2">
                    <IconDatabricks />
                    <span>Configure GitLab integration</span>
                </div>
            }
            onClose={props.onComplete}
        >
            <Form logic={gitlabSetupModalLogic} formKey="gitlabIntegration">
                <div className="gap-4 flex flex-col">
                    <LemonField name="serverHostname" label="Server Hostname">
                        <LemonInput type="text" placeholder="https://gitlab.com" defaultValue="https://gitlab.com" />
                    </LemonField>
                    <LemonField name="clientId" label="Project access token">
                        <LemonInput type="text" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" />
                    </LemonField>
                    <div className="flex justify-end">
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isGitLabIntegrationSubmitting}
                            onClick={submitGitLabIntegration}
                        >
                            Connect
                        </LemonButton>
                    </div>
                </div>
            </Form>
        </LemonModal>
    )
}
