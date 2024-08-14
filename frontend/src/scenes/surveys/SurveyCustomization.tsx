import { LemonButton, LemonCheckbox, LemonDialog, LemonInput, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { surveyLogic } from 'scenes/surveys/surveyLogic'

import {
    AvailableFeature,
    MultipleSurveyQuestion,
    RatingSurveyQuestion,
    SurveyAppearance as SurveyAppearanceType,
    SurveyQuestion,
    SurveyQuestionType,
} from '~/types'

import { defaultSurveyAppearance } from './constants'
import { surveysLogic } from './surveysLogic'

interface CustomizationProps {
    appearance: SurveyAppearanceType
    surveyQuestionItem: RatingSurveyQuestion | SurveyQuestion | MultipleSurveyQuestion
    onAppearanceChange: (appearance: SurveyAppearanceType) => void
}

interface WidgetCustomizationProps extends Omit<CustomizationProps, 'surveyQuestionItem'> {}

export function Customization({ appearance, surveyQuestionItem, onAppearanceChange }: CustomizationProps): JSX.Element {
    const { surveysStylingAvailable } = useValues(surveysLogic)
    const { surveyShufflingQuestionsAvailable, hasBranchingLogic } = useValues(surveyLogic)
    const { deleteBranchingLogic } = useActions(surveyLogic)
    const surveyShufflingQuestionsDisabledReason = surveyShufflingQuestionsAvailable
        ? ''
        : 'Please add more than one question to the survey to enable shuffling questions'
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    return (
        <>
            <div className="flex flex-col font-semibold">
                {!surveysStylingAvailable && (
                    <PayGateMini feature={AvailableFeature.SURVEYS_STYLING}>
                        <></>
                    </PayGateMini>
                )}
                <div className="mt-2">Background color</div>
                <LemonInput
                    value={appearance?.backgroundColor}
                    onChange={(backgroundColor) => onAppearanceChange({ ...appearance, backgroundColor })}
                    disabled={!surveysStylingAvailable}
                />
                <div className="mt-2">Border color</div>
                <LemonInput
                    value={appearance?.borderColor || defaultSurveyAppearance.borderColor}
                    onChange={(borderColor) => onAppearanceChange({ ...appearance, borderColor })}
                    disabled={!surveysStylingAvailable}
                />
                <>
                    <div className="mt-2">Position</div>
                    <div className="flex gap-1">
                        {['left', 'center', 'right'].map((position) => {
                            return (
                                <LemonButton
                                    key={position}
                                    type="tertiary"
                                    onClick={() => onAppearanceChange({ ...appearance, position })}
                                    active={appearance.position === position}
                                    disabledReason={
                                        surveysStylingAvailable
                                            ? null
                                            : 'Upgrade your plan to customize survey position.'
                                    }
                                >
                                    {position}
                                </LemonButton>
                            )
                        })}
                    </div>
                </>
                {surveyQuestionItem.type === SurveyQuestionType.Rating && (
                    <>
                        <div className="mt-2">Rating button color</div>
                        <LemonInput
                            value={appearance?.ratingButtonColor}
                            onChange={(ratingButtonColor) => onAppearanceChange({ ...appearance, ratingButtonColor })}
                            disabled={!surveysStylingAvailable}
                        />
                        <div className="mt-2">Rating button active color</div>
                        <LemonInput
                            value={appearance?.ratingButtonActiveColor}
                            onChange={(ratingButtonActiveColor) =>
                                onAppearanceChange({ ...appearance, ratingButtonActiveColor })
                            }
                            disabled={!surveysStylingAvailable}
                        />
                    </>
                )}
                <div className="mt-2">Button color</div>
                <LemonInput
                    value={appearance?.submitButtonColor}
                    onChange={(submitButtonColor) => onAppearanceChange({ ...appearance, submitButtonColor })}
                    disabled={!surveysStylingAvailable}
                />
                <div className="mt-2">Button text color</div>
                <LemonInput
                    value={appearance?.submitButtonTextColor}
                    onChange={(submitButtonTextColor) => onAppearanceChange({ ...appearance, submitButtonTextColor })}
                    disabled={!surveysStylingAvailable}
                />
                {surveyQuestionItem.type === SurveyQuestionType.Open && (
                    <>
                        <div className="mt-2">Placeholder text</div>
                        <LemonInput
                            value={appearance?.placeholder || defaultSurveyAppearance.placeholder}
                            onChange={(placeholder) => onAppearanceChange({ ...appearance, placeholder })}
                            disabled={!surveysStylingAvailable}
                        />
                    </>
                )}
                <div className="mt-4">
                    <LemonCheckbox
                        label={
                            <div className="flex items-center">
                                <span>Hide PostHog branding</span>
                            </div>
                        }
                        onChange={(checked) =>
                            guardAvailableFeature(AvailableFeature.WHITE_LABELLING, () =>
                                onAppearanceChange({ ...appearance, whiteLabel: checked })
                            )
                        }
                        checked={appearance?.whiteLabel}
                    />
                </div>
                <div className="mt-2">
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
                                            deleteBranchingLogic()
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
                            Delay survey popup after page load by at least{' '}
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
                                className="w-12"
                            />{' '}
                            seconds.
                        </div>
                    </LemonField.Pure>
                </div>
            </div>
        </>
    )
}

export function WidgetCustomization({ appearance, onAppearanceChange }: WidgetCustomizationProps): JSX.Element {
    return (
        <>
            <div className="mt-2">Feedback button type</div>
            <LemonSelect
                value={appearance.widgetType}
                onChange={(widgetType) => onAppearanceChange({ ...appearance, widgetType })}
                options={[
                    { label: 'Embedded tab', value: 'tab' },
                    { label: 'Custom', value: 'selector' },
                ]}
            />
            {appearance.widgetType === 'selector' ? (
                <>
                    <div className="mt-2">Class or ID selector</div>
                    <LemonInput
                        value={appearance.widgetSelector}
                        onChange={(widgetSelector) => onAppearanceChange({ ...appearance, widgetSelector })}
                        placeholder="ex: .feedback-button, #feedback-button"
                    />
                </>
            ) : (
                <>
                    <div className="mt-2">Label</div>
                    <LemonInput
                        value={appearance.widgetLabel}
                        onChange={(widgetLabel) => onAppearanceChange({ ...appearance, widgetLabel })}
                    />
                    <div className="mt-2">Background color</div>
                    <LemonInput
                        value={appearance.widgetColor}
                        onChange={(widgetColor) => onAppearanceChange({ ...appearance, widgetColor })}
                        placeholder="#e0a045"
                    />
                </>
            )}
        </>
    )
}
