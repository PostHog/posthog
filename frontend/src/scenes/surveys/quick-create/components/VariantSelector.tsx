import { useActions, useValues } from 'kea'

import { LemonLabel } from '@posthog/lemon-ui'

import { quickSurveyFormLogic } from 'scenes/surveys/quick-create/quickSurveyFormLogic'

import { FeatureFlagType } from '~/types'

export function VariantSelector({ flag }: { flag: FeatureFlagType }): JSX.Element {
    const { surveyForm } = useValues(quickSurveyFormLogic)
    const { updateConditions } = useActions(quickSurveyFormLogic)

    const targetVariant = surveyForm.conditions?.linkedFlagVariant || null

    const variants = flag?.filters?.multivariate?.variants || []
    const isMultivariate = variants.length > 1

    return (
        <>
            {isMultivariate && (
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
                            <span className="text-sm">All users with this flag enabled</span>
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
            )}
        </>
    )
}
