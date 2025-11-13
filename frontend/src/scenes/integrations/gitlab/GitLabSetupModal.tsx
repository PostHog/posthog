import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconGitLab } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, Link } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { GitLabSetupModalLogicProps, gitlabSetupModalLogic } from './gitlabSetupModalLogic'

export const GitLabSetupModal = (props: GitLabSetupModalLogicProps): JSX.Element => {
    const logic = gitlabSetupModalLogic(props)
    const { isGitlabIntegrationSubmitting } = useValues(logic)
    const { submitGitlabIntegration } = useActions(logic)

    return (
        <LemonModal
            isOpen={props.isOpen}
            title={
                <div className="flex items-center gap-2">
                    <IconGitLab />
                    <span>Configure GitLab integration</span>
                </div>
            }
            onClose={props.onComplete}
        >
            <Form logic={gitlabSetupModalLogic} formKey="gitlabIntegration">
                <div className="gap-4 flex flex-col">
                    <LemonField name="hostname" label="Hostname">
                        <LemonInput type="text" placeholder="https://gitlab.com" />
                    </LemonField>
                    <LemonField
                        name="projectId"
                        label="Project ID"
                        help={
                            <Link
                                target="_blank"
                                to="https://docs.gitlab.com/user/project/working_with_projects/#find-the-project-id"
                            >
                                Find your Project ID
                            </Link>
                        }
                    >
                        <LemonInput type="text" placeholder="1234567" />
                    </LemonField>
                    <LemonField
                        name="projectAccessToken"
                        label="Project access token"
                        help={
                            <>
                                Learn how to{' '}
                                <Link
                                    target="_blank"
                                    to="https://docs.gitlab.com/user/project/settings/project_access_tokens"
                                >
                                    create a project access token
                                </Link>
                            </>
                        }
                    >
                        <LemonInput
                            type="password"
                            placeholder="xxxxx-x_xxxxxxxxxxxxxxxxx-xxxxxxxxxxxxxxxxxx.xx.xxxxxxxxx"
                        />
                    </LemonField>
                    <div className="flex justify-end">
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isGitlabIntegrationSubmitting}
                            onClick={submitGitlabIntegration}
                        >
                            Connect
                        </LemonButton>
                    </div>
                </div>
            </Form>
        </LemonModal>
    )
}
