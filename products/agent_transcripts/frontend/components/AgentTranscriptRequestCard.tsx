import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { AnimatedWizardHog } from 'scenes/onboarding/shared/AnimatedWizardHog'
import { urls } from 'scenes/urls'

import type { AgentTranscriptRequestStage } from '../logics/agentTranscriptRequestLogic'
import type { AgentTranscriptRequestVariant } from '../logics/agentTranscriptVariant'

// The hog raises its staff once when the card appears, then idles.
const CAST_ON_APPEAR = 1

export interface AgentTranscriptRequestCardProps {
    variant: AgentTranscriptRequestVariant
    stage: AgentTranscriptRequestStage
    onOpen: () => void
    onDismiss: () => void
    className?: string
}

export function AgentTranscriptRequestCard({
    variant,
    stage,
    onOpen,
    onDismiss,
    className,
}: AgentTranscriptRequestCardProps): JSX.Element {
    const changesRequested = stage === 'changes_requested'

    return (
        <section
            aria-labelledby="agent-transcript-request-title"
            className={cn(
                'flex gap-3 rounded-lg border border-primary bg-surface-primary p-3 shadow',
                'animate-fade-in motion-reduce:animate-none',
                className
            )}
            data-attr="agent-transcript-request"
        >
            <AnimatedWizardHog castKey={CAST_ON_APPEAR} className="size-14 shrink-0 self-start" />
            <div className="flex min-w-0 flex-1 flex-col gap-1">
                <div className="flex items-start gap-1">
                    <h3 id="agent-transcript-request-title" className="m-0 flex-1 text-sm font-semibold leading-5">
                        {changesRequested
                            ? 'We asked for changes to your transcript'
                            : 'How did your agent set up PostHog?'}
                    </h3>
                    <LemonButton
                        icon={<IconX />}
                        size="xsmall"
                        type="tertiary"
                        tooltip="Dismiss"
                        aria-label="Dismiss"
                        onClick={onDismiss}
                        className="-mr-1 -mt-1"
                        data-attr="agent-transcript-request-dismiss"
                    />
                </div>
                <p className="m-0 text-xs text-secondary">
                    {changesRequested
                        ? 'See what to change, then upload a new file.'
                        : variant === 'test'
                          ? 'Share the transcript of that conversation to help us improve how agents set up PostHog. When we approve it, we email you a $20 merch store code.'
                          : 'Share the transcript of that conversation to help us improve how agents set up PostHog.'}
                </p>
                <div className="mt-1 flex flex-wrap gap-2">
                    <LemonButton
                        type="primary"
                        size="small"
                        to={urls.agentTranscript()}
                        onClick={onOpen}
                        data-attr="agent-transcript-request-open"
                    >
                        {changesRequested ? 'See requested changes' : 'Share transcript'}
                    </LemonButton>
                </div>
            </div>
        </section>
    )
}
