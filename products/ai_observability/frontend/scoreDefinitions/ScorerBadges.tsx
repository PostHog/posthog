import { LemonTag } from '@posthog/lemon-ui'

import type { ScoreDefinitionApi } from '../generated/api.schemas'
import { formatKindLabel } from './scoreDefinitionModalUtils'

export function ScorerBadges({
    scorer,
}: {
    scorer: Pick<ScoreDefinitionApi, 'kind' | 'scope' | 'calculation'>
}): JSX.Element {
    const experiment = scorer.scope === 'experiment'
    return (
        <span className="inline-flex flex-wrap items-center gap-1">
            <LemonTag type="muted" size="small" weight="normal">
                {formatKindLabel(scorer.kind)}
            </LemonTag>
            {(experiment || scorer.calculation === 'composite') && (
                <LemonTag type={experiment ? 'completion' : 'info'} size="small" weight="normal">
                    {experiment ? 'Experiment' : 'Composite'}
                </LemonTag>
            )}
        </span>
    )
}
