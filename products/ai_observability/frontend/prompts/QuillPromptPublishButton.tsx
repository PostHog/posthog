import { useActions, useValues } from 'kea'

import { Button } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { llmPromptLogic } from './llmPromptLogic'

/** Creates a new prompt, or publishes the edited one as its next version. */
export function QuillPromptPublishButton(): JSX.Element {
    const { isPromptFormSubmitting, isNewPrompt, isHistoricalVersion, nextVersion, isPromptFormDirty } =
        useValues(llmPromptLogic)
    const { submitPromptForm, requestPublish } = useActions(llmPromptLogic)

    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.LlmAnalytics}
            minAccessLevel={AccessControlLevel.Editor}
        >
            <Button
                variant="primary"
                onClick={isNewPrompt ? submitPromptForm : requestPublish}
                loading={isPromptFormSubmitting}
                disabledReason={
                    !isNewPrompt && !isHistoricalVersion && !isPromptFormDirty ? 'No changes to publish' : undefined
                }
                data-attr={isNewPrompt ? 'prompt-create-button' : 'prompt-save-button'}
            >
                {isNewPrompt ? 'Create prompt' : nextVersion ? `Publish v${nextVersion}` : 'Publish version'}
            </Button>
        </AccessControlAction>
    )
}
