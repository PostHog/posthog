import { LemonTag } from '@posthog/lemon-ui'

import { NewDefinitionProposal } from '../proposalTypes'

export function NewDefinitionDetail({ proposal }: { proposal: NewDefinitionProposal }): JSX.Element {
    const def = proposal.definition
    return (
        <div className="flex flex-col gap-4">
            <section className="border rounded p-4 bg-surface-primary">
                <div className="flex items-center gap-2 mb-2">
                    <span className="font-mono text-base">{def.name}</span>
                    <LemonTag type="primary" size="small">
                        {def.kind}
                    </LemonTag>
                    {def.entity ? (
                        <LemonTag type="option" size="small">
                            entity: {def.entity}
                        </LemonTag>
                    ) : null}
                </div>
                <p className="text-sm text-default">{def.description}</p>
            </section>

            {def.formulaPlainEnglish ? (
                <section>
                    <h4 className="text-xs uppercase tracking-wide text-muted-alt mb-1">Plain English</h4>
                    <p className="text-sm">{def.formulaPlainEnglish}</p>
                </section>
            ) : null}

            {def.formulaSql ? (
                <section>
                    <h4 className="text-xs uppercase tracking-wide text-muted-alt mb-1">Generated SQL</h4>
                    <pre className="text-xs bg-bg-3000 border rounded p-3 overflow-x-auto whitespace-pre">
                        {def.formulaSql}
                    </pre>
                </section>
            ) : null}

            {def.suggestedDimensions?.length ? (
                <section>
                    <h4 className="text-xs uppercase tracking-wide text-muted-alt mb-1">Suggested dimensions</h4>
                    <div className="flex flex-wrap gap-1.5">
                        {def.suggestedDimensions.map((d) => (
                            <LemonTag key={d} size="small">
                                {d}
                            </LemonTag>
                        ))}
                    </div>
                </section>
            ) : null}

            {def.suggestedOwner ? (
                <section>
                    <h4 className="text-xs uppercase tracking-wide text-muted-alt mb-1">Suggested owner</h4>
                    <span className="text-sm font-mono">{def.suggestedOwner}</span>
                </section>
            ) : null}
        </div>
    )
}
