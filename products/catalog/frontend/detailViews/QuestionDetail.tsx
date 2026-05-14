import { useState } from 'react'

import { LemonBanner, LemonTextArea } from '@posthog/lemon-ui'

import { LemonRadio } from 'lib/lemon-ui/LemonRadio'

import { QuestionProposal } from '../proposalTypes'

export function QuestionDetail({ proposal }: { proposal: QuestionProposal }): JSX.Element {
    const [choice, setChoice] = useState<string | undefined>(undefined)
    const [freeform, setFreeform] = useState('')

    return (
        <div className="flex flex-col gap-4">
            <LemonBanner type="info" className="text-sm">
                The agent paused work that depends on this answer. Choose an option — your answer is saved with the
                semantic layer so future agents follow it.
            </LemonBanner>

            <section className="border rounded p-4 bg-surface-primary">
                <h4 className="text-sm font-medium mb-3">{proposal.question}</h4>
                {proposal.options ? (
                    <LemonRadio
                        value={choice}
                        onChange={(v) => setChoice(v)}
                        options={proposal.options.map((o) => ({
                            value: o.id,
                            label: (
                                <div className="flex flex-col">
                                    <span className="font-mono text-sm">{o.label}</span>
                                    <span className="text-xs text-muted-alt">{o.rationale}</span>
                                </div>
                            ),
                        }))}
                    />
                ) : null}
                {proposal.allowFreeform ? (
                    <div className="mt-3">
                        <div className="text-xs text-muted-alt mb-1">Or describe a different approach</div>
                        <LemonTextArea
                            value={freeform}
                            onChange={setFreeform}
                            placeholder="e.g. We use a custom identifier set in HubSpot…"
                            minRows={2}
                            maxRows={4}
                        />
                    </div>
                ) : null}
            </section>
        </div>
    )
}
