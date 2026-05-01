import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { AnthropicSetupModalLogicProps, anthropicSetupModalLogic } from './anthropicSetupModalLogic'

export const AnthropicSetupModal = (props: AnthropicSetupModalLogicProps): JSX.Element => {
    const { isAnthropicIntegrationSubmitting } = useValues(anthropicSetupModalLogic(props))
    const { submitAnthropicIntegration } = useActions(anthropicSetupModalLogic(props))

    return (
        <LemonModal
            isOpen={props.isOpen}
            title="Configure Anthropic integration"
            onClose={props.onComplete}
            description="Connect an Anthropic API key to use Claude managed agents in PostHog workflows."
        >
            <Form logic={anthropicSetupModalLogic} formKey="anthropicIntegration">
                <div className="gap-4 flex flex-col">
                    <LemonField
                        name="apiKey"
                        label="API key"
                        help="Workspace API keys can be created in the Anthropic console under Settings → API keys."
                    >
                        <LemonInput type="password" placeholder="sk-ant-..." autoFocus />
                    </LemonField>
                    <LemonField
                        name="workspaceLabel"
                        label="Workspace label"
                        help="Optional label so you can tell multiple Anthropic workspaces apart."
                    >
                        <LemonInput type="text" placeholder="Production" />
                    </LemonField>
                    <div className="flex justify-end">
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isAnthropicIntegrationSubmitting}
                            onClick={submitAnthropicIntegration}
                        >
                            Connect
                        </LemonButton>
                    </div>
                </div>
            </Form>
        </LemonModal>
    )
}
