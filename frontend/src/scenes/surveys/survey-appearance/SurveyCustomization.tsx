import { useValues } from 'kea'

import { LemonCheckbox, LemonDialog, LemonDivider, LemonInput } from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { defaultSurveyAppearance } from 'scenes/surveys/constants'
import { SurveyAppearanceModal } from 'scenes/surveys/survey-appearance/SurveyAppearanceModal'
import {
    SurveyColorsAppearance,
    SurveyContainerAppearance,
} from 'scenes/surveys/survey-appearance/SurveyAppearanceSections'
import { CustomizationProps } from 'scenes/surveys/survey-appearance/types'

import { AvailableFeature, SurveyType } from '~/types'

import { surveysLogic } from '../surveysLogic'

export function Customization({
    survey,
    hasRatingButtons,
    hasPlaceholderText,
    hasBranchingLogic,
    onAppearanceChange,
    deleteBranchingLogic,
    validationErrors,
}: CustomizationProps): JSX.Element {
    const { surveysStylingAvailable } = useValues(surveysLogic)
    const surveyShufflingQuestionsAvailable = true
    const surveyShufflingQuestionsDisabledReason = surveyShufflingQuestionsAvailable
        ? ''
        : 'Please add more than one question to the survey to enable shuffling questions'
    const { guardAvailableFeature } = useValues(upgradeModalLogic)

    const surveyAppearance = { ...defaultSurveyAppearance, ...survey.appearance }

    return (
        <>
            <div className="flex flex-col gap-2">
                {!surveysStylingAvailable && (
                    <PayGateMini feature={AvailableFeature.SURVEYS_STYLING}>
                        <></>
                    </PayGateMini>
                )}
                <SurveyAppearanceModal
                    survey={survey}
                    onAppearanceChange={onAppearanceChange}
                    hasPlaceholderText={hasPlaceholderText}
                    hasRatingButtons={hasRatingButtons}
                    validationErrors={validationErrors}
                />
                {survey.type !== SurveyType.ExternalSurvey && (
                    <>
                        <SurveyContainerAppearance
                            appearance={surveyAppearance}
                            onAppearanceChange={onAppearanceChange}
                            validationErrors={validationErrors}
                            surveyType={survey.type}
                        />
                        <LemonDivider />
                    </>
                )}
                <SurveyColorsAppearance
                    appearance={surveyAppearance}
                    onAppearanceChange={onAppearanceChange}
                    validationErrors={validationErrors}
                    customizeRatingButtons={hasRatingButtons}
                    customizePlaceholderText={hasPlaceholderText}
                />
                <LemonDivider />
                <div className="flex flex-col gap-1">
                    <LemonCheckbox
                        label={
                            <div className="flex items-center">
                                <span>Hide PostHog branding</span>
                            </div>
                        }
                        onChange={(checked) =>
                            guardAvailableFeature(AvailableFeature.WHITE_LABELLING, () =>
                                onAppearanceChange({ whiteLabel: checked })
                            )
                        }
                        checked={survey.appearance?.whiteLabel}
                    />
                    <div className="flex flex-col gap-2">
                        <LemonCheckbox
                            disabledReason={surveyShufflingQuestionsDisabledReason}
                            label={
                                <div className="flex items-center">
                                    <span>Shuffle questions</span>
                                </div>
                            }
                            onChange={(checked) => {
                                if (checked && hasBranchingLogic) {
                                    onAppearanceChange({ shuffleQuestions: false })

                                    LemonDialog.open({
                                        title: 'Your survey has active branching logic',
                                        description: (
                                            <p className="py-2">
                                                Enabling this option will remove your branching logic. Are you sure you
                                                want to continue?
                                            </p>
                                        ),
                                        primaryButton: {
                                            children: 'Continue',
                                            status: 'danger',
                                            onClick: () => {
                                                if (deleteBranchingLogic) {
                                                    deleteBranchingLogic()
                                                }
                                                onAppearanceChange({ shuffleQuestions: true })
                                            },
                                        },
                                        secondaryButton: {
                                            children: 'Cancel',
                                        },
                                    })
                                } else {
                                    onAppearanceChange({ shuffleQuestions: checked })
                                }
                            }}
                            checked={survey.appearance?.shuffleQuestions}
                        />
                    </div>
                    {survey.type !== SurveyType.ExternalSurvey && (
                        <LemonField.Pure>
                            <div className="flex flex-row gap-2 items-center font-medium">
                                <LemonCheckbox
                                    checked={!!survey.appearance?.surveyPopupDelaySeconds}
                                    onChange={(checked) => {
                                        const surveyPopupDelaySeconds = checked ? 5 : undefined
                                        onAppearanceChange({ surveyPopupDelaySeconds })
                                    }}
                                />
                                Delay survey popup by at least{' '}
                                <LemonInput
                                    type="number"
                                    data-attr="survey-popup-delay-input"
                                    size="small"
                                    min={1}
                                    max={3600}
                                    value={survey.appearance?.surveyPopupDelaySeconds || NaN}
                                    onChange={(newValue) => {
                                        if (newValue && newValue > 0) {
                                            onAppearanceChange({ surveyPopupDelaySeconds: newValue })
                                        } else {
                                            onAppearanceChange({ surveyPopupDelaySeconds: undefined })
                                        }
                                    }}
                                    className="w-12 ignore-error-border"
                                />{' '}
                                seconds once the display conditions are met.
                            </div>
                        </LemonField.Pure>
                    )}
                </div>
            </div>
        </>
    )
}
