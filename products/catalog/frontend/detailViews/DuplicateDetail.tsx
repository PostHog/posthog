import clsx from 'clsx'

import { LemonTag } from '@posthog/lemon-ui'

import { DuplicateProposal } from '../proposalTypes'

export function DuplicateDetail({ proposal }: { proposal: DuplicateProposal }): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <section>
                <h4 className="text-xs uppercase tracking-wide text-muted-alt mb-2">Candidates</h4>
                <p className="text-xs text-muted-alt mb-2">
                    Suggested canonical highlighted — usually the most-used variant. Reviewer can override.
                </p>
                <div className="flex flex-col gap-2">
                    {proposal.candidates.map((c, i) => {
                        const isCanonical = i === proposal.recommendedCanonicalIndex
                        return (
                            <div
                                key={c.id}
                                className={clsx(
                                    'border rounded p-3',
                                    isCanonical ? 'border-primary-3000 bg-primary-3000-highlight' : 'bg-surface-primary'
                                )}
                            >
                                <div className="flex items-center gap-2 mb-1">
                                    <span className="font-mono text-sm">{c.name}</span>
                                    {isCanonical ? (
                                        <LemonTag type="primary" size="small">
                                            Canonical
                                        </LemonTag>
                                    ) : null}
                                    <span className="ml-auto text-xs text-muted-alt tabular-nums">
                                        {c.usage} insights
                                    </span>
                                </div>
                                <div className="text-xs text-default">{c.description}</div>
                                {c.owner ? <div className="text-xs text-muted-alt mt-1">owner: {c.owner}</div> : null}
                            </div>
                        )
                    })}
                </div>
            </section>
            <section className="text-xs text-muted-alt">
                Approving will rename the canonical variant, redirect references in {proposal.impact?.insights ?? 0}{' '}
                insights and {proposal.impact?.dashboards ?? 0} dashboards, and archive the other variants with
                backlinks.
            </section>
        </div>
    )
}
