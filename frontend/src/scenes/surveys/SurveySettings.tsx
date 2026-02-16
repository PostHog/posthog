import { useActions, useValues } from 'kea'
import { DeepPartialMap, ValidationErrorType } from 'kea-forms'
import { useState } from 'react'

import { IconGear } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSwitch, Link } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { surveysLogic } from 'scenes/surveys/surveysLogic'
import { sanitizeSurveyAppearance, validateSurveyAppearance } from 'scenes/surveys/utils'
import { teamLogic } from 'scenes/teamLogic'

import { AccessControlLevel, AccessControlResourceType, SurveyAppearance } from '~/types'

import { SurveyAppearancePreview } from './SurveyAppearancePreview'
import { NEW_SURVEY, defaultSurveyAppearance } from './constants'
import { Customization } from './survey-appearance/SurveyCustomization'

export function SurveyEnableToggle(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    return (
        <AccessControlAction resourceType={AccessControlResourceType.Survey} minAccessLevel={AccessControlLevel.Editor}>
            <LemonSwitch
                data-attr="opt-in-surveys-switch"
                onChange={(checked) => {
                    updateCurrentTeam({
                        surveys_opt_in: checked,
                    })
                }}
                label="Enable surveys"
                bordered
                checked={!!currentTeam?.surveys_opt_in}
                disabled={currentTeamLoading}
                disabledReason={currentTeamLoading ? 'Loading...' : undefined}
            />
        </AccessControlAction>
    )
}

export function SurveyDefaultAppearance(): JSX.Element {
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

        const hasErrors = errors && Object.values(errors).some((error) => error !== undefined)
        setValidationErrors(errors)

        if (hasErrors || !sanitizedAppearance) {
            return
        }

        updateCurrentTeam({
            survey_config: {
                ...currentTeam?.survey_config,
                appearance: sanitizedAppearance,
            },
        })
    }

    return (
        <AccessControlAction resourceType={AccessControlResourceType.Survey} minAccessLevel={AccessControlLevel.Editor}>
            {({ disabledReason }) => {
                if (disabledReason) {
                    return null
                }

                return (
                    <div className="space-y-4">
                        <div className="flex items-center justify-between">
                            {globalSurveyAppearanceConfigAvailable && (
                                <LemonButton type="primary" onClick={updateSurveySettings}>
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
                    </div>
                )
            }}
        </AccessControlAction>
    )
}

// Keep SurveySettings for modal usage
export function SurveySettings({ isModal = false }: { isModal?: boolean }): JSX.Element {
    if (isModal) {
        return <SurveyEnableToggle />
    }
    return (
        <div className="flex flex-col gap-4">
            <SurveyEnableToggle />
            <SurveyDefaultAppearance />
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
            Surveys are currently disabled for this project. Re-enable them in the settings, otherwise surveys will not
            be rendered in your app (either automatically or{' '}
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
