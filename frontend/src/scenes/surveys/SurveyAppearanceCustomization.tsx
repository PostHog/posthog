import { IconGear } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonDialog, LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { SurveyAppearanceModal } from 'scenes/surveys/SurveyAppearanceModal'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { PartialResponsesShuffleQuestionsBanner } from 'scenes/surveys/SurveyResponsesCollection'

import { AvailableFeature, SurveyType } from '~/types'

import { surveysLogic } from './surveysLogic'

export function SurveyAppearanceCustomization(): JSX.Element {
    const { survey, hasBranchingLogic, isAppearanceModalOpen } = useValues(surveyLogic)
    const { deleteBranchingLogic, setIsAppearanceModalOpen } = useActions(surveyLogic)
    const { surveysStylingAvailable } = useValues(surveysLogic)
    const surveyShufflingQuestionsAvailable = true
    const surveyShufflingQuestionsDisabledReason = surveyShufflingQuestionsAvailable
        ? ''
        : 'Please add more than one question to the survey to enable shuffling questions'

    return (
        <LemonField name="appearance" label="">
            {({ value: appearance, onChange: onAppearanceChange }) => (
                <div className="flex flex-col font-semibold">
                    {!surveysStylingAvailable && <PayGateMini feature={AvailableFeature.SURVEYS_STYLING} />}
                    {survey.type !== SurveyType.API && (
                        <LemonButton
                            type="secondary"
                            fullWidth
                            icon={<IconGear />}
                            onClick={() => setIsAppearanceModalOpen(true)}
                            disabled={!surveysStylingAvailable}
                        >
                            Customize Appearance
                        </LemonButton>
                    )}
                    {isAppearanceModalOpen && (
                        <SurveyAppearanceModal
                            visible={isAppearanceModalOpen}
                            onClose={() => setIsAppearanceModalOpen(false)}
                        />
                    )}
                    <div className="mt-2 flex flex-col gap-2">
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
                    </div>
                    <div className="mt-1">
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
                </div>
            )}
        </LemonField>
    )
}
