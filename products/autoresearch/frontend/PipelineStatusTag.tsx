import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { AutoresearchPipelineApi, AutoresearchPipelineStatusEnumApi } from './generated/api.schemas'
import { modelCardState } from './modelCardState'

type TagType = 'default' | 'success' | 'warning' | 'highlight' | 'completion'

interface StatusTag {
    type: TagType
    label: string
    description: string
}

const STATUS_TAG: Record<Exclude<AutoresearchPipelineStatusEnumApi, 'bootstrapping'>, StatusTag> = {
    draft: {
        type: 'default',
        label: 'Draft',
        description: 'Created but never trained. Start a training run to find a first champion.',
    },
    running: {
        type: 'success',
        label: 'Running',
        description: 'Live: a champion is promoted and the population is scored on schedule.',
    },
    converged: {
        type: 'completion',
        label: 'Converged',
        description: 'Champion is stable (budget spent or improvement plateaued); still scoring on schedule.',
    },
    paused: {
        type: 'warning',
        label: 'Paused',
        description: 'Scheduled scoring is on hold. Resume to continue scoring.',
    },
    archived: { type: 'default', label: 'Archived', description: 'Retired. No training or scoring runs.' },
}

// A model with no live version splits by what happened to its training runs, the same way as its card.
const NO_LIVE_MODEL_TAG: Record<'training' | 'not_live' | 'waiting_to_train', StatusTag> = {
    training: {
        type: 'highlight',
        label: 'Training',
        description: 'The first training run is starting or in progress. No model is live yet.',
    },
    not_live: {
        type: 'warning',
        label: 'Not live yet',
        description:
            "A training run found a model, but it couldn't go live. Nothing is scored until a model goes live.",
    },
    waiting_to_train: {
        type: 'warning',
        label: 'Waiting to train',
        description: 'No model is live yet, and the next training run has not started.',
    },
}

function statusTag(pipeline: AutoresearchPipelineApi): StatusTag {
    if (pipeline.status !== 'bootstrapping') {
        return STATUS_TAG[pipeline.status]
    }
    const state = modelCardState(pipeline)
    return state === 'not_live' || state === 'waiting_to_train' ? NO_LIVE_MODEL_TAG[state] : NO_LIVE_MODEL_TAG.training
}

/** Status tag with an explanatory tooltip, shared by the pipeline list and detail scenes. */
export function PipelineStatusTag({ pipeline }: { pipeline: AutoresearchPipelineApi }): JSX.Element {
    const { type, label, description } = statusTag(pipeline)
    return (
        <Tooltip title={description}>
            <LemonTag type={type}>{label}</LemonTag>
        </Tooltip>
    )
}
