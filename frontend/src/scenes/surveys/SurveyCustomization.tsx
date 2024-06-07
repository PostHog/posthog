import { LemonButton, LemonCheckbox, LemonInput, LemonSelect } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'

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
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
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
                        label={
                            <div className="flex items-center">
                                <span>Shuffle questions</span>
                            </div>
                        }
                        onChange={(checked) => onAppearanceChange({ ...appearance, shuffleQuestions: checked })}
                        checked={appearance?.shuffleQuestions}
                    />
                </div>
                <div className="mt-1">
                    <LemonField name="survey_popup_delay" className="font-medium">
                        {({ onChange }) => {
                            return (
                                <div className="flex flex-row gap-2 items-center">
                                    <LemonCheckbox
                                        checked={!!appearance?.surveyPopupDelay}
                                        onChange={(checked) => {
                                            const surveyPopupDelay = checked ? 60 : undefined
                                            onChange(surveyPopupDelay)
                                            onAppearanceChange({ ...appearance, surveyPopupDelay }) // TODO maybe I should explicitly differentiate between null and undefined.  Compiler seems happy enough for now.
                                        }}
                                    />
                                    Delay survey popup after page load by{' '}
                                    <LemonInput
                                        type="number"
                                        data-attr="survey-popup-delay-input" // TODO we need to hook into this
                                        size="small"
                                        min={1}
                                        value={appearance?.surveyPopupDelay || NaN}
                                        onChange={(newValue) => {
                                            if (newValue && newValue > 0) {
                                                onChange(newValue)
                                                onAppearanceChange({ ...appearance, surveyPopupDelay: newValue })
                                            } else {
                                                onChange(null)
                                                onAppearanceChange({ ...appearance, surveyPopupDelay: undefined })
                                            }
                                        }}
                                        className="w-12"
                                    />{' '}
                                    seconds.
                                </div>
                            )
                        }}
                    </LemonField>
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
