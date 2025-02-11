import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DeepPartialMap, ValidationErrorType } from 'kea-forms'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { useState } from 'react'
import { surveysLogic } from 'scenes/surveys/surveysLogic'
import { sanitizeSurveyAppearance, validateColor } from 'scenes/surveys/utils'
import { teamLogic } from 'scenes/teamLogic'

import { SurveyAppearance } from '~/types'

import { defaultSurveyAppearance, NEW_SURVEY } from './constants'
import { SurveyAppearancePreview } from './SurveyAppearancePreview'
import { Customization } from './SurveyCustomization'

export function SurveySettings(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { globalSurveyAppearanceConfigAvailable } = useValues(surveysLogic)
    const [validationErrors, setValidationErrors] = useState<DeepPartialMap<
        SurveyAppearance,
        ValidationErrorType
    > | null>(null)

    const [editableSurveyConfig, setEditableSurveyConfig] = useState(
        currentTeam?.survey_config?.appearance || defaultSurveyAppearance
    )

    const [templatedSurvey, setTemplatedSurvey] = useState(NEW_SURVEY)

    if (templatedSurvey.appearance === defaultSurveyAppearance) {
        templatedSurvey.appearance = editableSurveyConfig
    }

    const updateSurveySettings = (): void => {
        const sanitizedAppearance = sanitizeSurveyAppearance(editableSurveyConfig)
        const errors = {
            backgroundColor: validateColor(sanitizedAppearance?.backgroundColor, 'background color'),
            borderColor: validateColor(sanitizedAppearance?.borderColor, 'border color'),
            ratingButtonActiveColor: validateColor(
                sanitizedAppearance?.ratingButtonActiveColor,
                'rating button active color'
            ),
            ratingButtonColor: validateColor(sanitizedAppearance?.ratingButtonColor, 'rating button color'),
            submitButtonColor: validateColor(sanitizedAppearance?.submitButtonColor, 'button color'),
            submitButtonTextColor: validateColor(sanitizedAppearance?.submitButtonTextColor, 'button text color'),
        }

        // Check if there are any validation errors
        const hasErrors = Object.values(errors).some((error) => error !== undefined)
        setValidationErrors(errors)

        if (hasErrors || !sanitizedAppearance) {
            return
        }

        // If no errors, proceed with the update
        updateCurrentTeam({
            survey_config: {
                ...currentTeam?.survey_config,
                appearance: sanitizedAppearance,
            },
        })
    }

    return (
        <>
            <div className="flex items-center gap-2 mb-2">
                <LemonField.Pure className="mt-2" label="Appearance">
                    <span>These settings apply to new surveys in this organization.</span>
                </LemonField.Pure>

                <div className="flex-1" />
                {globalSurveyAppearanceConfigAvailable && (
                    <LemonButton type="primary" onClick={updateSurveySettings}>
                        Save settings
                    </LemonButton>
                )}
            </div>
            <LemonDivider />
            <div className="flex gap-2 mb-2 align-top">
                <Customization
                    appearance={editableSurveyConfig}
                    hasBranchingLogic={false}
                    customizeRatingButtons={true}
                    customizePlaceholderText={true}
                    onAppearanceChange={(appearance) => {
                        setEditableSurveyConfig({
                            ...editableSurveyConfig,
                            ...appearance,
                        })
                        setTemplatedSurvey({
                            ...templatedSurvey,
                            ...{ appearance: appearance },
                        })
                    }}
                    validationErrors={validationErrors}
                />
                <div className="flex-1" />
                <div className="mt-10 mr-5 survey-view">
                    {globalSurveyAppearanceConfigAvailable && (
                        <SurveyAppearancePreview survey={templatedSurvey} previewPageIndex={0} />
                    )}
                </div>
            </div>
        </>
    )
}

export function openSurveysSettingsDialog(): void {
    LemonDialog.open({
        title: 'Surveys settings',
        content: <SurveySettings />,
        width: 600,
        primaryButton: {
            children: 'Done',
        },
    })
}
