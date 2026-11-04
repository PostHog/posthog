import { IconCheck, IconMinus, IconX } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { EvalRollupOutcome } from '../types'

const MARKERS: Record<EvalRollupOutcome, { Icon: typeof IconCheck; className: string; label: string }> = {
    pass: { Icon: IconCheck, className: 'text-success', label: 'Evals passed on this step' },
    fail: { Icon: IconX, className: 'text-danger', label: 'An eval failed on this step' },
    unrated: { Icon: IconMinus, className: 'text-secondary', label: 'Evals on this step were not graded' },
}

export interface EvalOutcomeMarkerProps {
    outcome: EvalRollupOutcome
}

export function EvalOutcomeMarker({ outcome }: EvalOutcomeMarkerProps): JSX.Element {
    const { Icon, className, label } = MARKERS[outcome]
    return (
        <Tooltip title={label}>
            <span className={cn('flex shrink-0', className)} role="img" aria-label={label}>
                <Icon />
            </span>
        </Tooltip>
    )
}
