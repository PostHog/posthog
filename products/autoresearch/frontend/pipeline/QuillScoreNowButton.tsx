import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { AutoresearchModelRoleEnumApi } from '../generated/api.schemas'

export function QuillScoreNowButton(): JSX.Element | null {
    const { pipeline, models, scoreResultLoading, activeScoreRun } = useValues(autoresearchPipelineLogic)
    const { scoreNow } = useActions(autoresearchPipelineLogic)
    const hasChampion = models.some((m) => m.role === AutoresearchModelRoleEnumApi.Champion)
    if (!pipeline || pipeline.status === 'archived') {
        return null
    }
    return (
        <Button
            variant="outline"
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
            <IconRefresh />
            {activeScoreRun
                ? `Scoring… started ${dayjs(activeScoreRun.started_at ?? activeScoreRun.created_at).format('HH:mm')}`
                : 'Score now'}
        </Button>
    )
}
