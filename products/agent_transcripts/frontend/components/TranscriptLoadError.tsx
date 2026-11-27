import { useActions, useValues } from 'kea'

import { Button, Text } from '@posthog/quill'

import { agentTranscriptSceneLogic } from '../scenes/agentTranscriptSceneLogic'
import { TranscriptHero } from './TranscriptHero'
import { LoadErrorHog } from './transcriptHogs'

export function TranscriptLoadError(): JSX.Element {
    const { submissionLoading } = useValues(agentTranscriptSceneLogic)
    const { loadSubmission } = useActions(agentTranscriptSceneLogic)

    return (
        <TranscriptHero
            hog={<LoadErrorHog className="size-full" loading="eager" />}
            title="Couldn't load your organization's transcript"
            data-attr="agent-transcript-load-error"
        >
            <Text variant="muted" render={<p className="m-0" />}>
                Check your connection, then try again.
            </Text>
            <Button
                variant="primary"
                loading={submissionLoading}
                onClick={loadSubmission}
                data-attr="agent-transcript-load-retry"
            >
                Try again
            </Button>
        </TranscriptHero>
    )
}
