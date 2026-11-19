import { IconCheck, IconX } from '@posthog/icons'
import { LemonTagType } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import type { TraceEvaluationSummaryApi } from '../../../generated/api.schemas'
import { ChipButton } from './ChipButton'

export interface EvalsChipProps {
    summary: TraceEvaluationSummaryApi
    onClick: () => void
}

interface EvalCounts {
    passed: number
    graded: number
    unrated: number
}

function chipText({ passed, graded, unrated }: EvalCounts): string {
    return graded > 0 ? `Evals ${passed}/${graded} passed` : `Evals ${unrated} not graded`
}

function unratedNote({ graded, unrated }: EvalCounts): string | null {
    if (graded === 0 || unrated === 0) {
        return null
    }
    return unrated === 1 ? '1 more result was not graded' : `${unrated} more results were not graded`
}

function chipStyle({ passed, graded }: EvalCounts): { type: LemonTagType; icon: JSX.Element | undefined } {
    if (graded === 0) {
        return { type: 'default', icon: undefined }
    }
    return passed < graded ? { type: 'danger', icon: <IconX /> } : { type: 'success', icon: <IconCheck /> }
}

export function EvalsChip({ summary, onClick }: EvalsChipProps): JSX.Element | null {
    const { passed, failed, unrated } = summary
    if (passed + failed + unrated === 0) {
        return null
    }
    const chip = { passed, graded: passed + failed, unrated }
    const { type, icon } = chipStyle(chip)
    return (
        <Tooltip title={unratedNote(chip)}>
            <ChipButton type={type} icon={icon} onClick={onClick} data-attr="trace-view-evals-chip">
                {chipText(chip)}
            </ChipButton>
        </Tooltip>
    )
}
