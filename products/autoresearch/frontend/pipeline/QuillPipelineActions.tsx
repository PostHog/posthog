import { useActions, useValues } from 'kea'

import { IconPause, IconPlay } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'

export function QuillPipelineActions(): JSX.Element | null {
    const { pipeline, pipelineLoading } = useValues(autoresearchPipelineLogic)
    const { pausePipeline, resumePipeline } = useActions(autoresearchPipelineLogic)
    if (!pipeline) {
        return null
    }
    return (
        <>
            {pipeline.status === 'paused' ? (
                <Button
                    variant="outline"
                    onClick={() => resumePipeline()}
                    data-attr="autoresearch-model-resume"
                    loading={pipelineLoading}
                >
                    <IconPlay />
                    Resume
                </Button>
            ) : pipeline.status === 'running' ? (
                <Button
                    variant="outline"
                    onClick={() => pausePipeline()}
                    data-attr="autoresearch-model-pause"
                    loading={pipelineLoading}
                >
                    <IconPause />
                    Pause
                </Button>
            ) : null}
        </>
    )
}
