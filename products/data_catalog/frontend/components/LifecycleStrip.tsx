import { IconArrowRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import type { MetricStage, MetricStageCounts, MetricStatusFilter } from '../metricsLogic'

interface StageCardProps {
    stage: MetricStage
    title: string
    description: string
    count: number
    selected: boolean
    onToggle: (stage: MetricStage) => void
}

function StageCard({ stage, title, description, count, selected, onToggle }: StageCardProps): JSX.Element {
    return (
        <LemonButton
            type="secondary"
            active={selected}
            aria-pressed={selected}
            className="flex-1 min-w-48"
            fullWidth
            onClick={() => onToggle(stage)}
            // pinned: data-attr values feed autocapture dashboards
            data-attr={`data-catalog-stage-${stage}`}
        >
            <div className="flex flex-col gap-1 py-1 text-left font-normal">
                <div className="flex items-baseline gap-2">
                    <span className="font-semibold">{title}</span>
                    <span className={`text-xl font-semibold ${stage === 'drifted' && count > 0 ? 'text-danger' : ''}`}>
                        {count}
                    </span>
                </div>
                <span className="text-xs text-secondary">{description}</span>
            </div>
        </LemonButton>
    )
}

export interface LifecycleStripProps {
    counts: MetricStageCounts
    status: MetricStatusFilter
    onToggle: (stage: MetricStage) => void
}

export function LifecycleStrip({ counts, status, onToggle }: LifecycleStripProps): JSX.Element {
    return (
        <div className="flex flex-wrap items-stretch gap-2" data-attr="data-catalog-lifecycle-strip">
            <StageCard
                stage="proposed"
                title="Proposed"
                description="Waiting for review. Agents can use it, with a warning."
                count={counts.proposed}
                selected={status === 'proposed'}
                onToggle={onToggle}
            />
            <IconArrowRight className="text-secondary shrink-0 self-center" />
            <StageCard
                stage="approved"
                title="Approved"
                description="Reviewed by your team. Agents compute it from this definition."
                count={counts.approved}
                selected={status === 'approved'}
                onToggle={onToggle}
            />
            {/* Drift is a fault state, not a step after approval, so it stands apart from the flow. */}
            <div className="hidden @2xl:block self-stretch mx-1 border-l border-primary" />
            <StageCard
                stage="drifted"
                title="Drifted"
                description="The source insight changed or was deleted after this metric was saved. Agents use it with a warning."
                count={counts.drifted}
                selected={status === 'drifted'}
                onToggle={onToggle}
            />
        </div>
    )
}
