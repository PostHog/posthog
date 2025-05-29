import { LemonCheckbox, LemonDialog, LemonDivider, LemonInput, LemonSelect } from '@posthog/lemon-ui'
import { useValues } from 'kea'
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

import { AvailableFeature, SurveyAppearance, SurveyWidgetType } from '~/types'

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

                <SurveyContainerAppearance
                    appearance={{ ...defaultSurveyAppearance, ...survey.appearance }}
                    onAppearanceChange={onAppearanceChange}
                    validationErrors={validationErrors}
                    surveyType={survey.type}
                />
                <LemonDivider />
                <SurveyColorsAppearance
                    appearance={survey.appearance || defaultSurveyAppearance}
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
                                onAppearanceChange({ ...survey.appearance, whiteLabel: checked })
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
                                    onAppearanceChange({ ...survey.appearance, shuffleQuestions: false })

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
                                                onAppearanceChange({ ...survey.appearance, shuffleQuestions: true })
                                            },
                                        },
                                        secondaryButton: {
                                            children: 'Cancel',
                                        },
                                    })
                                } else {
                                    onAppearanceChange({ ...survey.appearance, shuffleQuestions: checked })
                                }
                            }}
                            checked={survey.appearance?.shuffleQuestions}
                        />
                    </div>
                    <LemonField.Pure>
                        <div className="flex flex-row gap-2 items-center font-medium">
                            <LemonCheckbox
                                checked={!!survey.appearance?.surveyPopupDelaySeconds}
                                onChange={(checked) => {
                                    const surveyPopupDelaySeconds = checked ? 5 : undefined
                                    onAppearanceChange({ ...survey.appearance, surveyPopupDelaySeconds })
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
                                        onAppearanceChange({
                                            ...survey.appearance,
                                            surveyPopupDelaySeconds: newValue,
                                        })
                                    } else {
                                        onAppearanceChange({
                                            ...survey.appearance,
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
        </>
    )
}

type WidgetCustomizationProps = Pick<CustomizationProps, 'onAppearanceChange' | 'validationErrors'> & {
    appearance: SurveyAppearance
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
