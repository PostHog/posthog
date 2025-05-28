import { LemonCheckbox, LemonDialog, LemonDivider, LemonInput, LemonSelect } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { DeepPartialMap, ValidationErrorType } from 'kea-forms'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { SurveyColorsAppearance, SurveyContainerAppearance } from 'scenes/surveys/survey-form/SurveyAppearanceSections'

import {
    AvailableFeature,
    SurveyAppearance,
    SurveyAppearance as SurveyAppearanceType,
    SurveyType,
    SurveyWidgetType,
} from '~/types'

import { surveysLogic } from './surveysLogic'

interface CustomizationProps {
    appearance: SurveyAppearanceType
    customizeRatingButtons: boolean
    customizePlaceholderText: boolean
    hasBranchingLogic: boolean
    deleteBranchingLogic?: () => void
    onAppearanceChange: (appearance: SurveyAppearanceType) => void
    validationErrors?: DeepPartialMap<SurveyAppearance, ValidationErrorType> | null
    type?: SurveyType
}

interface WidgetCustomizationProps extends Omit<CustomizationProps, 'surveyQuestionItem'> {}

export function Customization({
    appearance,
    customizeRatingButtons,
    customizePlaceholderText,
    hasBranchingLogic,
    onAppearanceChange,
    deleteBranchingLogic,
    validationErrors,
    type,
}: CustomizationProps): JSX.Element {
    const { surveysStylingAvailable } = useValues(surveysLogic)
    const surveyShufflingQuestionsAvailable = true
    const surveyShufflingQuestionsDisabledReason = surveyShufflingQuestionsAvailable
        ? ''
        : 'Please add more than one question to the survey to enable shuffling questions'
    const { guardAvailableFeature } = useValues(upgradeModalLogic)

    return (
        <>
            <div className="flex flex-col gap-2">
                {!surveysStylingAvailable && (
                    <PayGateMini feature={AvailableFeature.SURVEYS_STYLING}>
                        <></>
                    </PayGateMini>
                )}
                <SurveyContainerAppearance
                    appearance={appearance}
                    onAppearanceChange={onAppearanceChange}
                    validationErrors={validationErrors}
                    surveyType={type}
                />
                <LemonDivider />
                <SurveyColorsAppearance
                    appearance={appearance}
                    onAppearanceChange={onAppearanceChange}
                    validationErrors={validationErrors}
                    customizeRatingButtons={customizeRatingButtons}
                    customizePlaceholderText={customizePlaceholderText}
                />
                <LemonDivider />
                <div>
                    <div>
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
                    </div>
                    <div>
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
            </div>
        </>
    )
}

export function WidgetCustomization({
    appearance,
    onAppearanceChange,
    validationErrors,
}: WidgetCustomizationProps): JSX.Element {
    return (
        <>
            <LemonField.Pure label="Feedback button type" className="mt-2" labelClassName="font-normal">
                <LemonSelect
                    value={appearance.widgetType}
                    onChange={(widgetType) => onAppearanceChange({ ...appearance, widgetType })}
                    options={[
                        { label: 'Embedded tab', value: SurveyWidgetType.Tab },
                        { label: 'Custom', value: SurveyWidgetType.Selector },
                    ]}
                />
            </LemonField.Pure>
            {appearance.widgetType === SurveyWidgetType.Selector ? (
                <LemonField.Pure
                    className="mt-2"
                    label="CSS selector"
                    labelClassName="font-normal"
                    info="Enter a class or ID selector for the feedback button, like .feedback-button or #feedback-button. If you're using a custom theme, you can use the theme's class name."
                >
                    <LemonInput
                        value={appearance.widgetSelector}
                        onChange={(widgetSelector) => onAppearanceChange({ ...appearance, widgetSelector })}
                        placeholder="ex: .feedback-button, #feedback-button"
                    />
                    {validationErrors?.widgetSelector && <LemonField.Error error={validationErrors?.widgetSelector} />}
                </LemonField.Pure>
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
