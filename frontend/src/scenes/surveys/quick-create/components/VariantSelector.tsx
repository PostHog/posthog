import { useActions, useValues } from 'kea'

import { LemonLabel } from '@posthog/lemon-ui'

import { quickSurveyFormLogic } from 'scenes/surveys/quick-create/quickSurveyFormLogic'

import { MultivariateFlagVariant } from '~/types'

interface VariantSelectorProps {
    variants: MultivariateFlagVariant[]
    defaultOptionText?: string
}

export function VariantSelector({ variants, defaultOptionText }: VariantSelectorProps): JSX.Element | null {
    const { surveyForm } = useValues(quickSurveyFormLogic)
    const { updateConditions } = useActions(quickSurveyFormLogic)

    if (variants.length <= 1) {
        return null
    }

    const targetVariant = surveyForm.conditions?.linkedFlagVariant || null

    return (
        <div>
            <LemonLabel>Who should see this survey?</LemonLabel>
            <div className="space-y-2 mt-2">
                <label className="flex items-center gap-2 cursor-pointer">
                    <input
                        type="radio"
                        checked={targetVariant === null}
                        onChange={() => updateConditions({ linkedFlagVariant: undefined })}
                        className="cursor-pointer"
                    />
                    <span className="text-sm">{defaultOptionText ?? 'All users with this flag enabled'}</span>
                </label>
                {variants.map((v) => (
                    <label key={v.key} className="flex items-center gap-2 cursor-pointer">
                        <input
                            type="radio"
                            checked={targetVariant === v.key}
                            onChange={() => updateConditions({ linkedFlagVariant: v.key })}
                            className="cursor-pointer"
                        />
                        <span className="text-sm">
                            Only users in the <code className="text-xs">{v.key}</code> variant
                        </span>
                    </label>
                ))}
            </div>
        </div>
    )
}
