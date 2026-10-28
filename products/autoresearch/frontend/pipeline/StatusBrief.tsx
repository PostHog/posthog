import { useActions, useValues } from 'kea'

import { LemonCollapse, Tooltip } from '@posthog/lemon-ui'

import type { BriefModel } from '../agentSearch'
import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { SectionCard } from './SectionCard'

function ModelScores({ title, tooltip, model }: { title: string; tooltip: string; model: BriefModel }): JSX.Element {
    return (
        <div className="rounded bg-surface-secondary p-3 space-y-1 min-w-0" data-attr="autoresearch-brief-model">
            <Tooltip title={tooltip}>
                <div className="text-xs font-semibold text-muted uppercase tracking-wide truncate cursor-help">
                    {model.runNumber != null ? `${title} · run ${model.runNumber}` : title}
                </div>
            </Tooltip>
            <div className="flex items-baseline gap-2">
                <span className="text-lg font-bold tabular-nums">
                    {model.realizedScore != null ? model.realizedScore.toFixed(3) : 'Not checked yet'}
                </span>
                {model.realizedScore != null && <span className="text-xs text-secondary">on real outcomes</span>}
            </div>
            <div className="flex justify-between gap-2 text-xs text-secondary">
                <span>In training</span>
                <span className="tabular-nums">{model.holdoutScore != null ? model.holdoutScore.toFixed(3) : '—'}</span>
            </div>
        </div>
    )
}

/** The top of the Agent research tab: where the live model stands, how the newest scored model compares, and what comes next. */
export function StatusBrief(): JSX.Element | null {
    const { statusBrief } = useValues(autoresearchPipelineLogic)
    const { fullNotesOpened } = useActions(autoresearchPipelineLogic)
    if (!statusBrief) {
        return null
    }
    const { runNumber, readerSummary, factualLine, nextSteps, distillation, recommendedNext, live, scoredAlongside } =
        statusBrief
    return (
        <SectionCard
            title="Where things stand"
            actions={runNumber != null && <span className="text-xs text-muted">Updated after run {runNumber}</span>}
        >
            {(readerSummary || factualLine) && <p className="text-sm mb-0">{readerSummary || factualLine}</p>}
            {live && (
                <div className="grid grid-cols-1 @md:grid-cols-2 gap-2">
                    <ModelScores
                        title="Live"
                        tooltip="The model that scores people now. Real outcomes is the AUC against what people really did. In training is the AUC on held-out training data."
                        model={live}
                    />
                    {scoredAlongside && (
                        <ModelScores
                            title="Scored alongside"
                            tooltip="The newest model that PostHog scores next to the live one and checks against real outcomes. A run replaces the live model on its own when it wins."
                            model={scoredAlongside}
                        />
                    )}
                </div>
            )}
            {nextSteps.length > 0 && (
                <div className="text-sm">
                    <div className="text-muted">Next, the agent plans to:</div>
                    <ol className="list-decimal pl-5 mb-0">
                        {nextSteps.map((step) => (
                            <li key={step}>{step}</li>
                        ))}
                    </ol>
                </div>
            )}
            {(distillation || recommendedNext) && (
                <LemonCollapse
                    embedded
                    size="xsmall"
                    onChange={(key) => key === 'notes' && fullNotesOpened()}
                    panels={[
                        {
                            key: 'notes',
                            header: "Read the agent's full notes",
                            dataAttr: 'autoresearch-agent-full-notes',
                            content: (
                                <div className="space-y-1 text-sm text-secondary">
                                    {distillation && <div className="whitespace-pre-line">{distillation}</div>}
                                    {recommendedNext && (
                                        <div className="whitespace-pre-line">Next it plans to: {recommendedNext}</div>
                                    )}
                                </div>
                            ),
                        },
                    ]}
                />
            )}
        </SectionCard>
    )
}
