import { LemonBanner, LemonTag } from '@posthog/lemon-ui'

import { DriftProposal } from '../proposalTypes'

export function DriftDetail({ proposal }: { proposal: DriftProposal }): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <LemonBanner type="warning" className="text-sm">
                <span className="font-medium">Trigger: </span>
                {proposal.triggerEvent}
            </LemonBanner>

            <section className="flex items-center gap-2 text-sm">
                <span className="text-muted-alt">Target:</span>
                <span className="font-mono">{proposal.targetDefinition}</span>
                <LemonTag size="small">{proposal.targetKind}</LemonTag>
            </section>

            <section>
                <h4 className="text-xs uppercase tracking-wide text-muted-alt mb-2">Diff</h4>
                <div className="flex flex-col gap-3">
                    {proposal.diff.map((d) => (
                        <div key={d.field} className="border rounded overflow-hidden">
                            <div className="px-3 py-1.5 text-xs font-mono bg-bg-3000 border-b">{d.field}</div>
                            <div className="grid grid-cols-2 text-xs font-mono">
                                <div className="p-3 bg-danger-highlight border-r whitespace-pre-wrap">
                                    <div className="text-[10px] uppercase text-danger mb-1">before</div>
                                    {d.before}
                                </div>
                                <div className="p-3 bg-success-highlight whitespace-pre-wrap">
                                    <div className="text-[10px] uppercase text-success mb-1">after</div>
                                    {d.after}
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            </section>
        </div>
    )
}
