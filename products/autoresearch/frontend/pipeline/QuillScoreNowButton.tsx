import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { hasLiveModel } from '../modelCardState'

export function QuillScoreNowButton(): JSX.Element | null {
    const { pipeline, scoreResultLoading, activeScoreRun } = useValues(autoresearchPipelineLogic)
    const { scoreNow } = useActions(autoresearchPipelineLogic)
    if (!pipeline || pipeline.status === 'archived' || !hasLiveModel(pipeline)) {
        return null
    }
    return (
        <Button
            variant="outline"
            onClick={() => scoreNow()}
            data-attr="autoresearch-model-score"
            loading={scoreResultLoading || !!activeScoreRun}
            disabledReason={pipeline.status === 'paused' ? 'Resume the model to score it' : undefined}
        >
            <IconRefresh />
            {activeScoreRun
                ? `Scoring… started ${dayjs(activeScoreRun.started_at ?? activeScoreRun.created_at).format('HH:mm')}`
                : 'Score now'}
        </Button>
    )
}
