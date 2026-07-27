import { LemonTag } from '@posthog/lemon-ui'

import { ExperimentStatus } from '~/types'

import { getExperimentStatusColor, getExperimentStatusLabel } from '../experimentsLogic'

export function StatusTag({ status }: { status: ExperimentStatus }): JSX.Element {
    return (
        <LemonTag type={getExperimentStatusColor(status)} className="cursor-default">
            <b className="uppercase">{getExperimentStatusLabel(status)}</b>
        </LemonTag>
    )
}
