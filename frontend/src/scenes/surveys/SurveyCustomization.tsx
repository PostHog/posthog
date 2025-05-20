import { LemonButton, LemonCheckbox, LemonDialog, LemonInput, LemonSelect } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useValues } from 'kea'
import { DeepPartialMap, ValidationErrorType } from 'kea-forms'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { PartialResponsesShuffleQuestionsBanner } from 'scenes/surveys/SurveyResponsesCollection'

import {
    AvailableFeature,
    SurveyAppearance,
    SurveyAppearance as SurveyAppearanceType,
    SurveyPosition,
    SurveyType,
    SurveyWidgetType,
} from '~/types'

import { defaultSurveyAppearance, WEB_SAFE_FONTS } from './constants'
import { surveysLogic } from './surveysLogic'

const IGNORE_ERROR_BORDER_CLASS = 'ignore-error-border'

interface CustomizationProps {
    appearance: SurveyAppearanceType
    customizeRatingButtons: boolean
    customizePlaceholderText: boolean
    hasBranchingLogic: boolean
    deleteBranchingLogic?: () => void
    onAppearanceChange: (appearance: SurveyAppearanceType) => void
    isCustomFontsEnabled?: boolean
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
    isCustomFontsEnabled = false,
    validationErrors,
    type,
}: CustomizationProps): JSX.Element {
    const { surveysStylingAvailable } = useValues(surveysLogic)
    const surveyShufflingQuestionsAvailable = true
    const surveyShufflingQuestionsDisabledReason = surveyShufflingQuestionsAvailable
        ? ''
        : 'Please add more than one question to the survey to enable shuffling questions'
    const { guardAvailableFeature } = useValues(upgradeModalLogic)

    const isWidgetSurveyWithSelectorWidgetType =
        type === SurveyType.Widget && appearance.widgetType === SurveyWidgetType.Selector

    return (
        <>
            <div className="flex flex-col font-semibold">
                {!surveysStylingAvailable && (
                    <PayGateMini feature={AvailableFeature.SURVEYS_STYLING}>
                        <></>
                    </PayGateMini>
                )}
                <LemonField.Pure label="Background color">
                    <LemonInput
                        value={appearance?.backgroundColor}
                        onChange={(backgroundColor) => onAppearanceChange({ ...appearance, backgroundColor })}
                        disabled={!surveysStylingAvailable}
                        className={clsx(
                            validationErrors?.backgroundColor ? 'border-danger' : IGNORE_ERROR_BORDER_CLASS
                        )}
                    />
                    {validationErrors?.backgroundColor && (
                        <LemonField.Error error={validationErrors?.backgroundColor} />
                    )}
                </LemonField.Pure>
                <LemonField.Pure className="mt-2" label="Border color">
                    <LemonInput
                        value={appearance?.borderColor || defaultSurveyAppearance.borderColor}
                        onChange={(borderColor) => onAppearanceChange({ ...appearance, borderColor })}
                        disabled={!surveysStylingAvailable}
                        className={clsx(validationErrors?.borderColor ? 'border-danger' : IGNORE_ERROR_BORDER_CLASS)}
                    />
                    {validationErrors?.borderColor && <LemonField.Error error={validationErrors?.borderColor} />}
                </LemonField.Pure>
                <>
                    <LemonField.Pure
                        className="mt-2"
                        label="Position"
                        info={
                            isWidgetSurveyWithSelectorWidgetType
                                ? 'The "next to feedback button" option requires posthog.js version 1.235.2 or higher.'
                                : undefined
                        }
                    >
                        <div className="flex gap-1">
                            {Object.values(SurveyPosition).map((position) => {
                                if (
                                    position === SurveyPosition.NextToTrigger &&
                                    !isWidgetSurveyWithSelectorWidgetType
                                ) {
                                    return null
                                }
                                return (
                                    <LemonButton
                                        key={position}
                                        tooltip={
                                            position === SurveyPosition.NextToTrigger
                                                ? 'This option is only available for feedback button surveys. The survey will be displayed next to the chosen feedback button, based on the CSS selector you provided.'
                                                : undefined
                                        }
                                        type="tertiary"
                                        onClick={() => onAppearanceChange({ ...appearance, position })}
                                        active={appearance.position === position}
                                        disabledReason={
                                            surveysStylingAvailable
                                                ? null
                                                : 'Upgrade your plan to customize survey position.'
                                        }
                                    >
                                        {position === SurveyPosition.NextToTrigger
                                            ? 'next to feedback button'
                                            : position}
                                    </LemonButton>
                                )
                            })}
                        </div>
                    </LemonField.Pure>
                </>
                {customizeRatingButtons && (
                    <>
                        <LemonField.Pure className="mt-2" label="Rating button color">
                            <LemonInput
                                value={appearance?.ratingButtonColor}
                                onChange={(ratingButtonColor) =>
                                    onAppearanceChange({ ...appearance, ratingButtonColor })
                                }
                                disabled={!surveysStylingAvailable}
                                className={clsx(
                                    validationErrors?.ratingButtonColor ? 'border-danger' : IGNORE_ERROR_BORDER_CLASS
                                )}
                            />
                            {validationErrors?.ratingButtonColor && (
                                <LemonField.Error error={validationErrors?.ratingButtonColor} />
                            )}
                        </LemonField.Pure>
                        <LemonField.Pure className="mt-2" label="Rating button active color">
                            <LemonInput
                                value={appearance?.ratingButtonActiveColor}
                                onChange={(ratingButtonActiveColor) =>
                                    onAppearanceChange({ ...appearance, ratingButtonActiveColor })
                                }
                                disabled={!surveysStylingAvailable}
                                className={clsx(
                                    validationErrors?.ratingButtonActiveColor
                                        ? 'border-danger'
                                        : IGNORE_ERROR_BORDER_CLASS
                                )}
                            />
                            {validationErrors?.ratingButtonActiveColor && (
                                <LemonField.Error error={validationErrors?.ratingButtonActiveColor} />
                            )}
                        </LemonField.Pure>
                    </>
                )}
                <LemonField.Pure className="mt-2" label="Button color">
                    <LemonInput
                        value={appearance?.submitButtonColor}
                        onChange={(submitButtonColor) => onAppearanceChange({ ...appearance, submitButtonColor })}
                        disabled={!surveysStylingAvailable}
                        className={clsx(
                            validationErrors?.submitButtonColor ? 'border-danger' : IGNORE_ERROR_BORDER_CLASS
                        )}
                    />
                    {validationErrors?.submitButtonColor && (
                        <LemonField.Error error={validationErrors?.submitButtonColor} />
                    )}
                </LemonField.Pure>

                <LemonField.Pure className="mt-2" label="Button text color">
                    <LemonInput
                        value={appearance?.submitButtonTextColor}
                        onChange={(submitButtonTextColor) =>
                            onAppearanceChange({ ...appearance, submitButtonTextColor })
                        }
                        disabled={!surveysStylingAvailable}
                        className={clsx(
                            validationErrors?.submitButtonTextColor ? 'border-danger' : IGNORE_ERROR_BORDER_CLASS
                        )}
                    />
                    {validationErrors?.submitButtonTextColor && (
                        <LemonField.Error error={validationErrors?.submitButtonTextColor} />
                    )}
                </LemonField.Pure>

                <LemonField.Pure
                    className="mt-2"
                    label="Survey form zIndex"
                    info="If the survey popup is hidden behind another overlapping UI element, set this value higher than the overlapping element's zIndex."
                >
                    <LemonInput
                        type="text"
                        value={appearance?.zIndex}
                        onChange={(zIndex) => onAppearanceChange({ ...appearance, zIndex })}
                        disabled={!surveysStylingAvailable}
                        placeholder="2147482647"
                        defaultValue="2147482647"
                        className="ignore-error-border"
                    />
                </LemonField.Pure>
                {customizePlaceholderText && (
                    <LemonField.Pure className="mt-2" label="Placeholder text">
                        <LemonInput
                            value={
                                appearance?.placeholder !== undefined
                                    ? appearance.placeholder
                                    : defaultSurveyAppearance.placeholder
                            }
                            onChange={(placeholder) => onAppearanceChange({ ...appearance, placeholder })}
                            disabled={!surveysStylingAvailable}
                            className="ignore-error-border"
                        />
                    </LemonField.Pure>
                )}
                {isCustomFontsEnabled && (
                    <LemonField.Pure
                        className="mt-2"
                        label="Font family"
                        info="Custom font selection requires at least version 1.223.4 of posthog-js"
                    >
                        <LemonSelect
                            value={appearance?.fontFamily}
                            onChange={(fontFamily) => onAppearanceChange({ ...appearance, fontFamily })}
                            options={WEB_SAFE_FONTS.map((font) => {
                                return {
                                    label: (
                                        <span className={font.value.toLowerCase().replace(/\s/g, '-')}>
                                            {font.label}
                                        </span>
                                    ),
                                    value: font.value,
                                }
                            })}
                            className="ignore-error-border"
                        />
                    </LemonField.Pure>
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
                    {/* Only show the partial responses banner when the survey type is defined */}
                    {type && <PartialResponsesShuffleQuestionsBanner />}
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
