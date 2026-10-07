import { useActions, useValues } from 'kea'

import { IconPause, IconPlay, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog } from '@posthog/lemon-ui'

import { More } from 'lib/lemon-ui/LemonButton/More'

import { autoresearchLogic } from './autoresearchLogic'
import { AutoresearchPipelineApi } from './generated/api.schemas'

export function ModelCardMenu({ pipeline }: { pipeline: AutoresearchPipelineApi }): JSX.Element {
    const { mutatingPipelineIds } = useValues(autoresearchLogic)
    const { deletePipeline, pausePipeline, resumePipeline } = useActions(autoresearchLogic)
    const mutating = !!mutatingPipelineIds[pipeline.id]
    return (
        <More
            size="xsmall"
            data-attr="autoresearch-model-more"
            overlay={
                <>
                    {pipeline.status === 'running' && (
                        <LemonButton
                            fullWidth
                            icon={<IconPause />}
                            loading={mutating}
                            disabledReason={mutating ? 'Another change is still saving' : undefined}
                            onClick={() => pausePipeline(pipeline)}
                        >
                            Pause scheduled scoring
                        </LemonButton>
                    )}
                    {pipeline.status === 'paused' && (
                        <LemonButton
                            fullWidth
                            icon={<IconPlay />}
                            loading={mutating}
                            disabledReason={mutating ? 'Another change is still saving' : undefined}
                            onClick={() => resumePipeline(pipeline)}
                        >
                            Resume scheduled scoring
                        </LemonButton>
                    )}
                    <LemonButton
                        fullWidth
                        icon={<IconTrash />}
                        status="danger"
                        loading={mutating}
                        disabledReason={
                            mutating
                                ? 'Another change is still saving'
                                : pipeline.status === 'bootstrapping'
                                  ? 'Wait for the first training run to finish'
                                  : undefined
                        }
                        onClick={() => {
                            LemonDialog.open({
                                title: `Delete "${pipeline.name}"?`,
                                description:
                                    'The model, its training runs, and prediction metadata will be removed. Emitted autoresearch_prediction events stay in the events stream, and the prediction person property stays on each scored person.',
                                primaryButton: {
                                    children: 'Delete',
                                    status: 'danger',
                                    onClick: () => deletePipeline(pipeline.id, pipeline.name),
                                },
                                secondaryButton: { children: 'Cancel' },
                            })
                        }}
                    >
                        Delete model
                    </LemonButton>
                </>
            }
        />
    )
}
