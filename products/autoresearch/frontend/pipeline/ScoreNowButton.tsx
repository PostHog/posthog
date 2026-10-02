import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { AutoresearchModelRoleEnumApi } from '../generated/api.schemas'

/** Score-now action, gated on a champion existing. Reused in the title bar and empty states. */
export function ScoreNowButton(): JSX.Element | null {
    const { pipeline, models, scoreResultLoading, activeScoreRun } = useValues(autoresearchPipelineLogic)
    const { scoreNow } = useActions(autoresearchPipelineLogic)
    const hasChampion = models.some((m) => m.role === AutoresearchModelRoleEnumApi.Champion)
    if (!pipeline || pipeline.status === 'archived') {
        return null
    }
    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={<IconRefresh />}
            onClick={() => scoreNow()}
            data-attr="autoresearch-model-score"
            loading={scoreResultLoading || !!activeScoreRun}
            disabledReason={
                pipeline.status === 'paused'
                    ? 'Resume the model to score it'
                    : hasChampion
                      ? undefined
                      : 'Train a champion model first'
            }
        >
            {activeScoreRun
                ? `Scoring… started ${dayjs(activeScoreRun.started_at ?? activeScoreRun.created_at).format('HH:mm')}`
                : 'Score now'}
        </LemonButton>
    )
}
