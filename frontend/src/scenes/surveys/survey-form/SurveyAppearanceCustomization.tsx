import { IconGear } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDialog, LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { PartialResponsesShuffleQuestionsBanner } from 'scenes/surveys/SurveyResponsesCollection'

import { AvailableFeature, SurveyType } from '~/types'

export function SurveyAppearanceCustomization(): JSX.Element {
    const { hasBranchingLogic, survey, surveyShufflingQuestionsAvailable } = useValues(surveyLogic)
    const { deleteBranchingLogic, setIsAppearanceModalOpen } = useActions(surveyLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const surveyShufflingQuestionsDisabledReason = surveyShufflingQuestionsAvailable
        ? ''
        : 'Please add more than one question to the survey to enable shuffling questions'

    return (
        <LemonField name="appearance" label="">
            {({ value: appearance, onChange: onAppearanceChange }) => (
                <div className="flex flex-col font-semibold gap-1">
                    {survey.type !== SurveyType.API && (
                        <LemonButton
                            type="secondary"
                            fullWidth
                            icon={<IconGear />}
                            onClick={() => {
                                setIsAppearanceModalOpen(true)
                            }}
                        >
                            Change survey appearance
                        </LemonButton>
                    )}

                    <LemonCheckbox
                        label="Hide PostHog branding"
                        onChange={(checked) =>
                            guardAvailableFeature(AvailableFeature.WHITE_LABELLING, () =>
                                onAppearanceChange({ whiteLabel: checked })
                            )
                        }
                        checked={!!appearance.whiteLabel}
                    />
                    <LemonCheckbox
                        disabledReason={surveyShufflingQuestionsDisabledReason}
                        label={
                            <div className="flex items-center">
                                <span>Shuffle questions</span>
                            </div>
                        }
                        onChange={(checked) => {
                            if (checked && hasBranchingLogic) {
                                onAppearanceChange({ ...appearance, shuffleQuestions: false })

                                LemonDialog.open({
                                    title: 'Your survey has active branching logic',
                                    description: (
                                        <p className="py-2">
                                            Enabling this option will remove your branching logic. Are you sure you want
                                            to continue?
                                        </p>
                                    ),
                                    primaryButton: {
                                        children: 'Continue',
                                        status: 'danger',
                                        onClick: () => {
                                            if (deleteBranchingLogic) {
                                                deleteBranchingLogic()
                                            }
                                            onAppearanceChange({ ...appearance, shuffleQuestions: true })
                                        },
                                    },
                                    secondaryButton: {
                                        children: 'Cancel',
                                    },
                                })
                            } else {
                                onAppearanceChange({ ...appearance, shuffleQuestions: checked })
                            }
                        }}
                        checked={appearance?.shuffleQuestions}
                    />
                    <PartialResponsesShuffleQuestionsBanner />
                    <LemonField.Pure>
                        <div className="flex flex-row gap-2 items-center font-medium">
                            <LemonCheckbox
                                checked={!!appearance?.surveyPopupDelaySeconds}
                                onChange={(checked) => {
                                    const surveyPopupDelaySeconds = checked ? 5 : undefined
                                    onAppearanceChange({ ...appearance, surveyPopupDelaySeconds })
                                }}
                            />
                            Delay survey popup by at least{' '}
                            <LemonInput
                                type="number"
                                data-attr="survey-popup-delay-input"
                                size="small"
                                min={1}
                                max={3600}
                                value={appearance?.surveyPopupDelaySeconds || NaN}
                                onChange={(newValue) => {
                                    if (newValue && newValue > 0) {
                                        onAppearanceChange({ ...appearance, surveyPopupDelaySeconds: newValue })
                                    } else {
                                        onAppearanceChange({
                                            ...appearance,
                                            surveyPopupDelaySeconds: undefined,
                                        })
                                    }
                                }}
                                className="w-12 ignore-error-border"
                            />{' '}
                            seconds once the display conditions are met.
                        </div>
                    </LemonField.Pure>
                </div>
            )}
        </LemonField>
    )
}
