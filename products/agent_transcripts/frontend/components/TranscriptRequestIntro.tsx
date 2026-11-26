import { Highlight, Text } from '@posthog/quill'

import { AnimatedWizardHog } from 'scenes/onboarding/shared/AnimatedWizardHog'

import type { AgentTranscriptRequestVariant } from '../logics/agentTranscriptVariant'
import { TranscriptHero } from './TranscriptHero'
import { TranscriptRewardNote } from './TranscriptRewardNote'

// The hog raises its staff once when the page opens, as it does on the request card.
const CAST_ON_APPEAR = 1

export interface TranscriptRequestIntroProps {
    variant: AgentTranscriptRequestVariant | null
}

export function TranscriptRequestIntro({ variant }: TranscriptRequestIntroProps): JSX.Element {
    return (
        <TranscriptHero
            hog={<AnimatedWizardHog castKey={CAST_ON_APPEAR} className="size-full" />}
            title={
                <>
                    How did <Highlight animate>your agent</Highlight> set up PostHog?
                </>
            }
            data-attr="agent-transcript-intro"
        >
            <Text variant="muted" render={<p className="m-0" />}>
                You set up PostHog with an AI agent. The transcript of that conversation shows us where the agent did
                well and where it got stuck, so we can improve how agents set up PostHog.
            </Text>
            {variant === 'test' && <TranscriptRewardNote />}
        </TranscriptHero>
    )
}
