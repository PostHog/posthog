import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { hasLiveModel } from '../modelCardState'

/** Score-now action, shown only while the model has a live version. Reused in the title bar and empty states. */
export function ScoreNowButton(): JSX.Element | null {
    const { pipeline, scoreResultLoading, activeScoreRun } = useValues(autoresearchPipelineLogic)
    const { scoreNow } = useActions(autoresearchPipelineLogic)
    if (!pipeline || pipeline.status === 'archived' || !hasLiveModel(pipeline)) {
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
            disabledReason={pipeline.status === 'paused' ? 'Resume the model to score it' : undefined}
        >
            {activeScoreRun
                ? `Scoring… started ${dayjs(activeScoreRun.started_at ?? activeScoreRun.created_at).format('HH:mm')}`
                : 'Score now'}
        </LemonButton>
    )
}
