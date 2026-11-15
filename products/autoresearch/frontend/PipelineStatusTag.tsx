import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { AutoresearchPipelineStatusEnumApi } from './generated/api.schemas'

const STATUS_TAG_TYPE: Record<
    AutoresearchPipelineStatusEnumApi,
    'default' | 'success' | 'warning' | 'highlight' | 'completion'
> = {
    draft: 'default',
    bootstrapping: 'highlight',
    running: 'success',
    converged: 'completion',
    paused: 'warning',
    archived: 'default',
}

const STATUS_LABEL: Record<AutoresearchPipelineStatusEnumApi, string> = {
    draft: 'Draft',
    bootstrapping: 'Bootstrapping',
    running: 'Running',
    converged: 'Converged',
    paused: 'Paused',
    archived: 'Archived',
}

const STATUS_DESCRIPTION: Record<AutoresearchPipelineStatusEnumApi, string> = {
    draft: 'Created but never trained. Start a training run to find a first champion.',
    bootstrapping: 'First training run in progress. No champion has been promoted yet.',
    running: 'Live: a champion is promoted and the population is scored on schedule.',
    converged: 'Champion is stable (budget spent or improvement plateaued); still scoring on schedule.',
    paused: 'Scheduled scoring is on hold. Resume to continue scoring.',
    archived: 'Retired. No training or scoring runs.',
}

/** Status tag with an explanatory tooltip, shared by the pipeline list and detail scenes. */
export function PipelineStatusTag({ status }: { status: AutoresearchPipelineStatusEnumApi }): JSX.Element {
    return (
        <Tooltip title={STATUS_DESCRIPTION[status]}>
            <LemonTag type={STATUS_TAG_TYPE[status]}>{STATUS_LABEL[status]}</LemonTag>
        </Tooltip>
    )
}
