import { URL_MATCHING_HINTS } from 'lib/components/UrlMatchingHints'

import { ActionStepType } from '~/types'

import {
    ACTION_STEP_MATCHING_LABEL,
    ActionStepMatchingField,
    actionStepMatching,
    withActionStepMatching,
    withActionStepOption,
} from '../utils/actionStepEdits'
import { QuillActionStepField } from './QuillActionStepField'
import { QuillActionStepMatchingToggle } from './QuillActionStepMatchingToggle'

const MATCHING_OPTIONS = Object.entries(ACTION_STEP_MATCHING_LABEL).map(([value, label]) => ({ value, label }))

/** A text field of a match group that also picks how its value is compared. */
export function QuillActionStepMatchedField({
    step,
    sendStep,
    field,
    label,
    caption,
    disabledReason,
}: {
    step: ActionStepType
    sendStep: (step: ActionStepType) => void
    field: ActionStepMatchingField
    label: string
    caption?: React.ReactNode
    disabledReason?: string
}): JSX.Element {
    const matching = actionStepMatching(step, field)

    return (
        <QuillActionStepField
            label={label}
            caption={caption}
            hint={
                field === 'url' && step.url_matching && step.url_matching in URL_MATCHING_HINTS
                    ? URL_MATCHING_HINTS[step.url_matching as keyof typeof URL_MATCHING_HINTS]
                    : undefined
            }
            value={step[field] || ''}
            onChange={(value) => sendStep(withActionStepOption(step, field, value))}
            disabledReason={disabledReason}
            labelExtra={
                <QuillActionStepMatchingToggle
                    label={`How ${label.toLowerCase()} matches`}
                    options={MATCHING_OPTIONS}
                    value={matching}
                    onChange={(value) => sendStep(withActionStepMatching(step, field, value))}
                    disabledReason={disabledReason}
                />
            }
        />
    )
}
