import { IconCheck, IconX } from '@posthog/icons'
import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { EvalsChipData } from '../types'

export interface EvalsChipProps {
    chip: EvalsChipData
    onClick: () => void
}

function chipText({ passed, graded, unrated }: EvalsChipData): string {
    return graded > 0 ? `Evals ${passed}/${graded} passed` : `Evals ${unrated} not graded`
}

function unratedNote({ graded, unrated }: EvalsChipData): string | null {
    if (graded === 0 || unrated === 0) {
        return null
    }
    return unrated === 1 ? '1 more result was not graded' : `${unrated} more results were not graded`
}

function chipStyle({ passed, graded }: EvalsChipData): { type: LemonTagType; icon: JSX.Element | undefined } {
    if (graded === 0) {
        return { type: 'default', icon: undefined }
    }
    return passed < graded ? { type: 'danger', icon: <IconX /> } : { type: 'success', icon: <IconCheck /> }
}

export function EvalsChip({ chip, onClick }: EvalsChipProps): JSX.Element {
    const { type, icon } = chipStyle(chip)
    return (
        <Tooltip title={unratedNote(chip)}>
            <button type="button" onClick={onClick} data-attr="trace-view-evals-chip" className="rounded">
                <LemonTag type={type} icon={icon} weight="normal" className="cursor-pointer">
                    <span>{chipText(chip)}</span>
                </LemonTag>
            </button>
        </Tooltip>
    )
}
