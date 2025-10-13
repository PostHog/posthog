import { useActions, useValues } from 'kea'
import { DeepPartialMap, ValidationErrorType } from 'kea-forms'
import { useState } from 'react'

import { IconGear } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, LemonSwitch, Link } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { surveysLogic } from 'scenes/surveys/surveysLogic'
import { sanitizeSurveyAppearance, validateSurveyAppearance } from 'scenes/surveys/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType, SurveyAppearance } from '~/types'

import { SurveyAppearancePreview } from './SurveyAppearancePreview'
import { NEW_SURVEY, defaultSurveyAppearance } from './constants'
import { Customization } from './survey-appearance/SurveyCustomization'

interface Props {
    isModal?: boolean
}

function SurveyPopupToggle(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    return (
        <div className="flex flex-col gap-1">
            {currentTeam?.surveys_opt_in !== undefined && (
                <AccessControlAction
                    resourceType={AccessControlResourceType.Survey}
                    minAccessLevel={AccessControlLevel.Editor}
                >
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
                </AccessControlAction>
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

    const [templatedSurvey, setTemplatedSurvey] = useState({
        ...NEW_SURVEY,
        appearance: {
            ...NEW_SURVEY.appearance,
            ...currentTeam?.survey_config?.appearance,
        },
    })

    if (templatedSurvey.appearance === defaultSurveyAppearance) {
        templatedSurvey.appearance = editableSurveyConfig
    }

    const updateSurveySettings = (): void => {
        const sanitizedAppearance = sanitizeSurveyAppearance(editableSurveyConfig)
        const errors = sanitizedAppearance && validateSurveyAppearance(sanitizedAppearance, true, templatedSurvey.type)

        // Check if there are any validation errors
        const hasErrors = errors && Object.values(errors).some((error) => error !== undefined)
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

            <AccessControlAction
                resourceType={AccessControlResourceType.Survey}
                minAccessLevel={AccessControlLevel.Editor}
            >
                {({ disabledReason }) => {
                    // The disabledReason is set if the user doesn't have access to the survey resource
                    if (disabledReason) {
                        return null
                    }

                    return (
                        <>
                            <div className="flex items-center gap-1 flex-1 justify-between">
                                <LemonField.Pure label="Default appearance" className="text-base gap-1">
                                    <span className="text-sm">
                                        These settings apply to new surveys in this organization.
                                    </span>
                                </LemonField.Pure>
                                {globalSurveyAppearanceConfigAvailable && (
                                    <LemonButton type="primary" onClick={updateSurveySettings} className="">
                                        Save appearance changes
                                    </LemonButton>
                                )}
                            </div>

                            <div className="flex gap-8">
                                <div className="min-w-1/2">
                                    <Customization
                                        survey={templatedSurvey}
                                        hasBranchingLogic={false}
                                        hasRatingButtons={true}
                                        hasPlaceholderText={true}
                                        onAppearanceChange={(appearance) => {
                                            const newAppearance = {
                                                ...editableSurveyConfig,
                                                ...appearance,
                                            }
                                            const errors = validateSurveyAppearance(
                                                newAppearance,
                                                true,
                                                templatedSurvey.type
                                            )
                                            setValidationErrors(errors)
                                            setEditableSurveyConfig(newAppearance)
                                            setTemplatedSurvey({
                                                ...templatedSurvey,
                                                appearance: newAppearance,
                                            })
                                        }}
                                        validationErrors={validationErrors}
                                    />
                                </div>
                                {globalSurveyAppearanceConfigAvailable && (
                                    <div className="max-w-1/2 pt-8 pr-8 overflow-auto">
                                        <SurveyAppearancePreview survey={templatedSurvey} previewPageIndex={0} />
                                    </div>
                                )}
                            </div>
                        </>
                    )
                }}
            </AccessControlAction>
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
