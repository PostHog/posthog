import { IconCheck, IconMinus, IconX } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import { EvalRollupOutcome } from '../types'

const MARKERS: Record<EvalRollupOutcome, { Icon: typeof IconCheck; className: string; label: string }> = {
    pass: { Icon: IconCheck, className: 'text-success', label: 'Evals passed' },
    fail: { Icon: IconX, className: 'text-danger', label: 'Evals failed' },
    unrated: { Icon: IconMinus, className: 'text-secondary', label: 'Evals not graded' },
}

export interface EvalOutcomeMarkerProps {
    outcome: EvalRollupOutcome
}

export function EvalOutcomeMarker({ outcome }: EvalOutcomeMarkerProps): JSX.Element {
    const { Icon, className, label } = MARKERS[outcome]
    return <Icon className={cn('shrink-0', className)} role="img" aria-label={label} />
}
