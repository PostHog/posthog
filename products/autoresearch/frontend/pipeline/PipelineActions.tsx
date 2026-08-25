import { useActions, useValues } from 'kea'

import { IconPause, IconPlay } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'

export function PipelineActions(): JSX.Element | null {
    const { pipeline, pipelineLoading } = useValues(autoresearchPipelineLogic)
    const { pausePipeline, resumePipeline } = useActions(autoresearchPipelineLogic)
    if (!pipeline) {
        return null
    }
    return (
        <>
            {pipeline.status === 'paused' ? (
                <LemonButton
                    type="secondary"
                    icon={<IconPlay />}
                    size="small"
                    onClick={() => resumePipeline()}
                    loading={pipelineLoading}
                >
                    Resume
                </LemonButton>
            ) : pipeline.status === 'running' || pipeline.status === 'bootstrapping' ? (
                <LemonButton
                    type="secondary"
                    icon={<IconPause />}
                    size="small"
                    onClick={() => pausePipeline()}
                    loading={pipelineLoading}
                >
                    Pause
                </LemonButton>
            ) : null}
        </>
    )
}
