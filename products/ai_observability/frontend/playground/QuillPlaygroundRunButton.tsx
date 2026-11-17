import { useActions, useValues } from 'kea'

import { IconPlay } from '@posthog/icons'
import { Button, Spinner } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { llmPlaygroundRunLogic } from './llmPlaygroundRunLogic'

export function QuillPlaygroundRunButton(): JSX.Element {
    const { submitting, hasRunnablePrompts } = useValues(llmPlaygroundRunLogic)
    const { submitPrompt, abortRun } = useActions(llmPlaygroundRunLogic)

    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.LlmPlayground}
            minAccessLevel={AccessControlLevel.Editor}
        >
            <Button
                variant={submitting ? 'destructive-outline' : 'primary'}
                onClick={() => (submitting ? abortRun() : submitPrompt())}
                disabledReason={
                    submitting ? undefined : !hasRunnablePrompts ? 'Add messages to at least one prompt' : undefined
                }
                data-attr="llma-playground-run-button"
            >
                {submitting ? <Spinner /> : <IconPlay />}
                <span>{submitting ? 'Stop' : 'Run'}</span>
            </Button>
        </AccessControlAction>
    )
}
