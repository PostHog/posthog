import { LemonBanner, LemonCard, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { urls } from 'scenes/urls'

import type { CloudAgentRunApi } from '../generated/api.schemas'
import { CloudAgentRunStatusReasonEnumApi } from '../generated/api.schemas'
import { INFERENCE_MODE_DISPLAY, REASONING_EFFORT_LABELS } from '../utils/runStatus'
import { RunOutput } from './RunOutput'
import { RunStatusTag } from './RunStatusTag'

const FAILURE_REASONS: CloudAgentRunStatusReasonEnumApi[] = [
    CloudAgentRunStatusReasonEnumApi.ProvisionFailed,
    CloudAgentRunStatusReasonEnumApi.UnexpectedFailure,
]
const LIMIT_REASONS: CloudAgentRunStatusReasonEnumApi[] = [
    CloudAgentRunStatusReasonEnumApi.TimedOut,
    CloudAgentRunStatusReasonEnumApi.CreditSpent,
]

function Fact({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex min-w-0 flex-col">
            <dt className="text-secondary text-xs font-normal">{label}</dt>
            <dd className="m-0 break-words">{children}</dd>
        </div>
    )
}

/** The status of a run, why it stopped, the prompt, the result, and the facts about how it ran. */
export function RunSummaryCard({ run }: { run: CloudAgentRunApi }): JSX.Element {
    const repository = run.repositories[0]
    const reason = run.status_reason
    const isFailure = !!reason && FAILURE_REASONS.includes(reason)
    const isLimit = !!reason && LIMIT_REASONS.includes(reason)
    const showBanner = (isFailure || isLimit) && !!run.status_detail

    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-3 p-4" data-attr="cloud-agents-run-summary">
            <div className="flex flex-wrap items-center gap-2">
                <RunStatusTag status={run.status} reason={reason} />
                {!showBanner && run.status_detail && <span className="text-secondary">{run.status_detail}</span>}
            </div>
            {showBanner && <LemonBanner type={isFailure ? 'error' : 'warning'}>{run.status_detail}</LemonBanner>}
            <div>
                <div className="text-secondary text-xs">Prompt</div>
                <p className="m-0 whitespace-pre-wrap break-words" translate="no">
                    {run.prompt}
                </p>
            </div>
            {run.result.summary && (
                <div>
                    <div className="text-secondary text-xs">Result</div>
                    <div className="break-words" translate="no">
                        <LemonMarkdown lowKeyHeadings disableImages="all">
                            {run.result.summary}
                        </LemonMarkdown>
                    </div>
                </div>
            )}
            {run.result.output !== null && <RunOutput output={run.result.output} />}
            <dl className="m-0 grid grid-cols-2 gap-3 border-t pt-3 @min-[40rem]/main-content:grid-cols-4">
                <Fact label="Repository">
                    <span translate="no">{repository?.name ?? 'None'}</span>
                </Fact>
                <Fact label="Branch">
                    <span translate="no">{repository?.initial_branch ?? 'Default branch'}</span>
                </Fact>
                <Fact label="Preset">
                    {run.preset ? <Link to={urls.cloudAgentPreset(run.preset.id)}>{run.preset.name}</Link> : 'None'}
                </Fact>
                <Fact label="Model">
                    <span translate="no">{run.config.model ?? 'Default'}</span>
                </Fact>
                <Fact label="Reasoning effort">
                    {run.config.reasoning_effort ? REASONING_EFFORT_LABELS[run.config.reasoning_effort] : 'Default'}
                </Fact>
                <Fact label="Model provider">{INFERENCE_MODE_DISPLAY[run.config.inference]?.label}</Fact>
                <Fact label="Idle time">{run.config.idle_minutes} minutes</Fact>
                <Fact label="Started by">
                    <span translate="no">{run.created_by?.email ?? (run.caller === 'api' ? 'API' : 'Unknown')}</span>
                </Fact>
                <Fact label="Created">
                    <TZLabel time={run.created_at} />
                </Fact>
                <Fact label="Last stopped">{run.ended_at ? <TZLabel time={run.ended_at} /> : 'Not stopped yet'}</Fact>
            </dl>
        </LemonCard>
    )
}
