import { useState } from 'react'

import { Field, FieldDescription, FieldLabel } from '@posthog/quill'

import { TagsCombobox } from 'lib/components/Scenes/TagsCombobox'

import { ActionStepType, PropertyOperator } from '~/types'

import { actionStepScreenNames, withActionStepScreenName } from '../utils/actionStepEdits'
import { SCREEN_NAME_MATCHING_LABEL, type ScreenNameMatching } from '../utils/screenName'
import { QuillActionStepField } from './QuillActionStepField'
import { QuillActionStepMatchingToggle } from './QuillActionStepMatchingToggle'

const SCREEN_NAME_DESCRIPTION =
    'Matches the $screen_name property on $screen events sent by the mobile SDKs (iOS, Android, React Native, Flutter). This is the mobile equivalent of a pageview URL.'
const OPERATOR_OPTIONS = Object.entries(SCREEN_NAME_MATCHING_LABEL).map(([value, label]) => ({ value, label }))

export function QuillActionStepScreenName({
    step,
    sendStep,
    disabledReason,
}: {
    step: ActionStepType
    sendStep: (step: ActionStepType) => void
    disabledReason?: string
}): JSX.Element {
    const { screenNames, operator: filterOperator } = actionStepScreenNames(step)
    // An empty filter isn't saved, so the step can't hold the operator until a value is typed. Keeping it here stops
    // "matches exactly" from snapping back to the default. The field remounts when the step stops being a screen.
    const [operator, setOperator] = useState<ScreenNameMatching>(filterOperator ?? PropertyOperator.IContains)

    const setFilter = (value: string | string[], op: ScreenNameMatching): void => {
        sendStep(withActionStepScreenName(step, value, op))
    }
    const operatorToggle = (
        <QuillActionStepMatchingToggle
            label="How the screen name matches"
            options={OPERATOR_OPTIONS}
            value={operator}
            onChange={(value) => {
                const op = value as ScreenNameMatching
                setOperator(op)
                setFilter(op === PropertyOperator.Exact ? screenNames : (screenNames[0] ?? ''), op)
            }}
            disabledReason={disabledReason}
        />
    )

    // Only "matches exactly" takes several names, which the query turns into an IN() list.
    if (operator !== PropertyOperator.Exact) {
        return (
            <QuillActionStepField
                label="Screen name"
                labelExtra={operatorToggle}
                caption={SCREEN_NAME_DESCRIPTION}
                value={screenNames[0] ?? ''}
                onChange={(value) => setFilter(value, operator)}
                placeholder="e.g. HomeScreen"
                disabledReason={disabledReason}
                dataAttr="edit-action-screen-name-input"
            />
        )
    }

    return (
        <Field>
            <div className="flex flex-wrap items-center justify-between gap-2">
                <FieldLabel>Screen name</FieldLabel>
                {operatorToggle}
            </div>
            <FieldDescription>{SCREEN_NAME_DESCRIPTION}</FieldDescription>
            <TagsCombobox
                value={screenNames}
                onChange={(names) => setFilter(names, operator)}
                options={[]}
                allowCustomValues
                customValueNoun="screen name"
                placeholder="e.g. HomeScreen, Settings"
                disabledReason={disabledReason}
                dataAttr="edit-action-screen-name-input"
            />
        </Field>
    )
}
