import { LemonCheckbox, LemonInput, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { surveyLogic } from 'scenes/surveys/surveyLogic'

import { SurveySchedule } from '~/types'

export function SurveyWidgetCustomization(): JSX.Element {
    const { survey, surveyErrors } = useValues(surveyLogic)
    const { setSurveyValue } = useActions(surveyLogic)

    const validationErrors = surveyErrors?.appearance

    return (
        <div className="flex flex-col gap-2">
            <LemonField name="appearance" label="">
                {({ value: appearance, onChange: onAppearanceChange }) => (
                    <>
                        <LemonField.Pure label="Feedback button type">
                            <LemonSelect
                                value={appearance.widgetType}
                                onChange={(widgetType) => onAppearanceChange({ ...appearance, widgetType })}
                                options={[
                                    { label: 'Embedded tab', value: 'tab' },
                                    { label: 'Custom', value: 'selector' },
                                ]}
                            />
                        </LemonField.Pure>
                        {survey.appearance?.widgetType === 'selector' ? (
                            <LemonField.Pure
                                label="CSS selector"
                                info="Enter a class or ID selector for the feedback button, like .feedback-button or #feedback-button. If you're using a custom theme, you can use the theme's class name."
                            >
                                <LemonInput
                                    value={appearance.widgetSelector}
                                    onChange={(widgetSelector) => onAppearanceChange({ ...appearance, widgetSelector })}
                                    placeholder="ex: .feedback-button, #feedback-button"
                                />
                                {validationErrors?.widgetSelector && (
                                    <LemonField.Error error={validationErrors?.widgetSelector} />
                                )}
                            </LemonField.Pure>
                        ) : (
                            <>
                                <LemonField.Pure label="Button label">
                                    <LemonInput
                                        value={appearance.widgetLabel}
                                        onChange={(widgetLabel) => onAppearanceChange({ ...appearance, widgetLabel })}
                                    />
                                </LemonField.Pure>
                                <LemonField.Pure label="Background color">
                                    <LemonInput
                                        value={appearance.widgetColor}
                                        onChange={(widgetColor) => onAppearanceChange({ ...appearance, widgetColor })}
                                        placeholder="#e0a045"
                                    />
                                </LemonField.Pure>
                            </>
                        )}
                    </>
                )}
            </LemonField>
            <LemonCheckbox
                label="Allow survey to be displayed every time the button is clicked"
                checked={survey.schedule === SurveySchedule.Always}
                onChange={(checked) => {
                    setSurveyValue('schedule', checked ? SurveySchedule.Always : SurveySchedule.Once)
                    setSurveyValue('iteration_count', 0)
                    setSurveyValue('iteration_frequency_days', 0)
                }}
            />
        </div>
    )
}
