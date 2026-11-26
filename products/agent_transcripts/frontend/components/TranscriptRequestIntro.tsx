import type { AgentTranscriptRequestVariant } from '../logics/agentTranscriptVariant'

export interface TranscriptRequestIntroProps {
    variant: AgentTranscriptRequestVariant | null
    retentionDays: number
}

export function TranscriptRequestIntro({ variant, retentionDays }: TranscriptRequestIntroProps): JSX.Element {
    return (
        <section className="flex flex-col gap-3" data-attr="agent-transcript-intro">
            <p className="m-0">
                You set up PostHog with an AI agent. The transcript of that conversation shows us where the agent did
                well and where it got stuck, so we can improve how agents set up PostHog.
            </p>
            <div className="flex flex-col gap-1">
                <h2 className="m-0 text-sm font-semibold">What happens to the file</h2>
                <ul className="m-0 flex list-disc flex-col gap-1 pl-5">
                    <li>The PostHog team uses it only to improve setup with AI agents.</li>
                    <li>PostHog staff review each transcript.</li>
                    <li>
                        We delete the file <span translate="no">{retentionDays}</span> days after you upload it.
                    </li>
                </ul>
            </div>
            {variant === 'test' && (
                <p className="m-0" data-attr="agent-transcript-reward">
                    When we approve your transcript, we email you a $20 code for the PostHog merch store.
                </p>
            )}
        </section>
    )
}
