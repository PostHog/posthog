import { LemonButton, LemonCheckbox, LemonInput, LemonSelect } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'

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
    const { whitelabelAvailable, surveysStylingAvailable } = useValues(surveysLogic)
    return (
        <>
            <div className="flex flex-col">
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
                                            : 'Subscribe to surveys to customize survey position.'
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
                {surveyQuestionItem.type === SurveyQuestionType.Open && (
                    <>
                        <div className="mt-2">Placeholder</div>
                        <LemonInput
                            value={appearance?.placeholder || defaultSurveyAppearance.placeholder}
                            onChange={(placeholder) => onAppearanceChange({ ...appearance, placeholder })}
                            disabled={!surveysStylingAvailable}
                        />
                    </>
                )}
                <div className="mt-2">
                    <LemonCheckbox
                        label={
                            <div className="flex items-center">
                                <span>Hide PostHog branding</span>
                            </div>
                        }
                        onChange={(checked) => onAppearanceChange({ ...appearance, whiteLabel: checked })}
                        checked={appearance?.whiteLabel}
                        disabledReason={
                            !whitelabelAvailable ? 'Upgrade to any paid plan to hide PostHog branding' : null
                        }
                    />
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
