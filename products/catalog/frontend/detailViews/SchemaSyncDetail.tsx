import { useState } from 'react'

import { LemonCheckbox, LemonTag } from '@posthog/lemon-ui'

import { SchemaSyncProposal } from '../proposalTypes'

export function SchemaSyncDetail({ proposal }: { proposal: SchemaSyncProposal }): JSX.Element {
    const [selected, setSelected] = useState<Record<string, boolean>>(() =>
        Object.fromEntries(proposal.addedColumns.map((c) => [c.column, c.preselected]))
    )
    const total = Object.values(selected).filter(Boolean).length

    return (
        <div className="flex flex-col gap-4">
            <section className="flex items-center gap-2 text-sm">
                <span className="text-muted-alt">Source:</span>
                <span className="font-mono">{proposal.sourceTable}</span>
            </section>

            <section>
                <h4 className="text-xs uppercase tracking-wide text-muted-alt mb-2">New columns</h4>
                <div className="flex flex-col gap-1">
                    {proposal.addedColumns.map((c) => (
                        <label
                            key={c.column}
                            className="flex items-center gap-3 p-2 border rounded hover:bg-fill-highlight-50 cursor-pointer"
                        >
                            <LemonCheckbox
                                checked={selected[c.column]}
                                onChange={(v) =>
                                    setSelected((s) => ({
                                        ...s,
                                        [c.column]: v,
                                    }))
                                }
                            />
                            <span className="font-mono text-sm flex-1">{c.column}</span>
                            <LemonTag size="small">{c.type}</LemonTag>
                            <LemonTag type="option" size="small">
                                {c.suggestedRole.replace('_', ' ')}
                            </LemonTag>
                        </label>
                    ))}
                </div>
                <div className="text-xs text-muted-alt mt-2">
                    {total} of {proposal.addedColumns.length} columns selected. Approving adds them as suggested.
                </div>
            </section>
        </div>
    )
}
