import { IconGear } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, LemonSwitch, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DeepPartialMap, ValidationErrorType } from 'kea-forms'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useState } from 'react'
import { surveysLogic } from 'scenes/surveys/surveysLogic'
import { sanitizeSurveyAppearance, validateColor } from 'scenes/surveys/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SurveyAppearance } from '~/types'

import { defaultSurveyAppearance, NEW_SURVEY } from './constants'
import { Customization } from './survey-appearance/SurveyCustomization'
import { SurveyAppearancePreview } from './SurveyAppearancePreview'

interface Props {
    isModal?: boolean
}

function SurveyPopupToggle(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    return (
        <div className="flex flex-col gap-1">
            {currentTeam?.surveys_opt_in !== undefined && (
                <LemonSwitch
                    data-attr="opt-in-surveys-switch"
                    onChange={(checked) => {
                        updateCurrentTeam({
                            surveys_opt_in: checked,
                        })
                    }}
                    fullWidth
                    bordered={false}
                    label="Enable surveys"
                    labelClassName="text-base font-semibold"
                    checked={currentTeam.surveys_opt_in}
                    className="p-0"
                    disabled={currentTeamLoading}
                    disabledReason={currentTeamLoading ? 'Loading...' : undefined}
                />
            )}
            <span>
                Please note your website needs to have the{' '}
                <Link to={urls.settings('project', 'snippet')}>PostHog snippet</Link> or at least version 1.81.1 of{' '}
                <Link
                    to="https://posthog.com/docs/libraries/js?utm_campaign=surveys&utm_medium=in-product"
                    target="_blank"
                >
                    posthog-js
                </Link>{' '}
                directly installed. For more details, check out our{' '}
                <Link
                    to="https://posthog.com/docs/surveys/installation?utm_campaign=surveys&utm_medium=in-product"
                    target="_blank"
                >
                    docs
                </Link>
                .
            </span>
        </div>
    )
}

export function SurveySettings({ isModal = false }: Props): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { globalSurveyAppearanceConfigAvailable } = useValues(surveysLogic)
    const [validationErrors, setValidationErrors] = useState<DeepPartialMap<
        SurveyAppearance,
        ValidationErrorType
    > | null>(null)

    const [editableSurveyConfig, setEditableSurveyConfig] = useState({
        ...defaultSurveyAppearance,
        ...currentTeam?.survey_config?.appearance,
    })

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

    if (isModal) {
        return <SurveyPopupToggle />
    }

    return (
        <div className="flex flex-col gap-2">
            <SurveyPopupToggle />
            <LemonDivider className="m-0" />

            <div className="flex items-center gap-1 flex-1 justify-between">
                <LemonField.Pure label="Appearance" className="text-base gap-1">
                    <span className="text-sm">These settings apply to new surveys in this organization.</span>
                </LemonField.Pure>
                {globalSurveyAppearanceConfigAvailable && (
                    <LemonButton type="primary" onClick={updateSurveySettings} className="">
                        Save appearance changes
                    </LemonButton>
                )}
            </div>

            <div className="flex gap-16">
                <Customization
                    survey={templatedSurvey}
                    hasBranchingLogic={false}
                    customizeRatingButtons
                    customizePlaceholderText
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
                <div className="mt-10 mr-5 survey-view">
                    {globalSurveyAppearanceConfigAvailable && (
                        <SurveyAppearancePreview survey={templatedSurvey} previewPageIndex={0} />
                    )}
                </div>
            </div>
        </div>
    )
}

function openSurveysSettingsDialog(): void {
    LemonDialog.open({
        title: 'Surveys settings',
        content: <SurveySettings isModal />,
        width: 600,
        primaryButton: {
            children: 'Done',
        },
    })
}

export function SurveysDisabledBanner(): JSX.Element | null {
    const { showSurveysDisabledBanner } = useValues(surveysLogic)

    const { featureFlags } = useValues(featureFlagLogic)
    const settingLevel = featureFlags[FEATURE_FLAGS.ENVIRONMENTS] ? 'environment' : 'project'

    if (!showSurveysDisabledBanner) {
        return null
    }

    return (
        <LemonBanner
            type="warning"
            action={{
                type: 'secondary',
                icon: <IconGear />,
                onClick: () => openSurveysSettingsDialog(),
                children: 'Configure',
            }}
            className="mb-2"
        >
            Surveys are currently disabled for this {settingLevel}. Re-enable them in the settings, otherwise surveys
            will not be rendered in your app (either automatically or{' '}
            <Link to="https://posthog.com/docs/surveys/implementing-custom-surveys#rendering-surveys-programmatically">
                using the <code>renderSurvey</code> function
            </Link>
            ). Surveys API is enabled if you are{' '}
            <Link
                to="https://posthog.com/docs/surveys/implementing-custom-surveys#fetching-surveys-manually"
                target="_blank"
            >
                fetching and rendering them manually
            </Link>
            .
        </LemonBanner>
    )
}
