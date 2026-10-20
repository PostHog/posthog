import { LemonCheckbox, LemonDialog, LemonDivider, LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { BACK_BUTTON_DEFAULT_TEXT, NewSurvey } from 'scenes/surveys/constants'

import { Survey, SurveyAppearance } from '~/types'

interface SurveyBehaviorOptionsProps {
    survey: Survey | NewSurvey
    onAppearanceChange: (appearance: Partial<SurveyAppearance>) => void
    disabledReason?: string
    hasBranchingLogic?: boolean
    deleteBranchingLogic?: () => void
}

// Shared by the classic editor and the guided wizard so both expose the same behavior toggles.
export function SurveyBehaviorOptions({
    survey,
    onAppearanceChange,
    disabledReason,
    hasBranchingLogic,
    deleteBranchingLogic,
}: SurveyBehaviorOptionsProps): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <LemonCheckbox
                disabledReason={disabledReason}
                label="Shuffle questions"
                onChange={(checked) => {
                    if (checked && hasBranchingLogic) {
                        onAppearanceChange({ shuffleQuestions: false })

                        LemonDialog.open({
                            title: 'Your survey has active branching logic',
                            description: (
                                <p className="py-2">
                                    Enabling this option will remove your branching logic. Are you sure you want to
                                    continue?
                                </p>
                            ),
                            primaryButton: {
                                children: 'Continue',
                                status: 'danger',
                                onClick: () => {
                                    deleteBranchingLogic?.()
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
            <LemonDivider className="my-0" />
            <LemonCheckbox
                disabledReason={disabledReason}
                label="Allow going back to previous questions"
                onChange={(checked) =>
                    onAppearanceChange({
                        allowGoBack: checked,
                        backButtonText: checked ? survey.appearance?.backButtonText : undefined,
                    })
                }
                checked={survey.appearance?.allowGoBack}
            />
            {survey.appearance?.allowGoBack && (
                <LemonField.Pure label="Back button text" className="ml-6">
                    <LemonInput
                        size="small"
                        placeholder={BACK_BUTTON_DEFAULT_TEXT}
                        value={survey.appearance?.backButtonText ?? ''}
                        onChange={(backButtonText) => onAppearanceChange({ backButtonText })}
                        className="ignore-error-border max-w-xs"
                        disabledReason={disabledReason}
                    />
                </LemonField.Pure>
            )}
        </div>
    )
}
