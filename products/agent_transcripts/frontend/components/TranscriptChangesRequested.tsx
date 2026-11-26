import { Callout, CalloutContent, CalloutDescription, CalloutIcon, CalloutTitle, Text } from '@posthog/quill'

import type { AgentTranscriptRequestVariant } from '../logics/agentTranscriptVariant'
import { TranscriptHero } from './TranscriptHero'
import { ChangesRequestedHog } from './transcriptHogs'
import { TranscriptRewardNote } from './TranscriptRewardNote'

export interface TranscriptChangesRequestedProps {
    reviewMessage: string | null
    variant: AgentTranscriptRequestVariant | null
}

export function TranscriptChangesRequested({ reviewMessage, variant }: TranscriptChangesRequestedProps): JSX.Element {
    return (
        <TranscriptHero
            hog={<ChangesRequestedHog className="size-full" loading="eager" />}
            title="The PostHog team asked for changes"
            data-attr="agent-transcript-changes-requested"
        >
            {reviewMessage && (
                <Callout tone="warning" className="text-left">
                    <CalloutIcon />
                    <CalloutContent>
                        <CalloutTitle>What to change</CalloutTitle>
                        <CalloutDescription className="whitespace-pre-wrap">{reviewMessage}</CalloutDescription>
                    </CalloutContent>
                </Callout>
            )}
            <Text variant="muted" render={<p className="m-0" />}>
                Make the changes, then upload the new file below.
            </Text>
            {variant === 'test' && <TranscriptRewardNote />}
        </TranscriptHero>
    )
}
