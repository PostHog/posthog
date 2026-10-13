import { IconCheck, IconClock, IconMinus, IconWarning, IconX } from '@posthog/icons'
import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { EvalOutcome } from '../types'

const OUTCOME_STYLES: Record<EvalOutcome, { type: LemonTagType; icon: JSX.Element | undefined }> = {
    pass: { type: 'success', icon: <IconCheck /> },
    fail: { type: 'danger', icon: <IconX /> },
    error: { type: 'danger', icon: <IconWarning /> },
    pending: { type: 'default', icon: <IconClock /> },
    inconclusive: { type: 'muted', icon: <IconMinus /> },
    unrated: { type: 'default', icon: undefined },
}

export interface EvalOutcomeTagProps {
    outcome: EvalOutcome
    label: string
}

export function EvalOutcomeTag({ outcome, label }: EvalOutcomeTagProps): JSX.Element {
    const { type, icon } = OUTCOME_STYLES[outcome]
    return (
        <LemonTag type={type} icon={icon} size="small" className="max-w-full" title={label}>
            <span className="truncate">{label}</span>
        </LemonTag>
    )
}
