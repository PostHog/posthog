import { DeepPartialMap, ValidationErrorType } from 'kea-forms'

import { SurveyAppearance } from '~/types'

import { QuillSurveyAppearanceInput } from './QuillSurveyAppearanceInput'

export function QuillSurveyColorsAppearance({
    appearance,
    onAppearanceChange,
    validationErrors,
    customizeRatingButtons,
    customizePlaceholderText,
    disabledReason,
}: {
    appearance: SurveyAppearance
    onAppearanceChange: (appearance: SurveyAppearance) => void
    validationErrors?: DeepPartialMap<SurveyAppearance, ValidationErrorType> | null
    customizeRatingButtons: boolean
    customizePlaceholderText: boolean
    disabledReason?: string
}): JSX.Element {
    return (
        <div className="@container">
            <div className="grid grid-cols-1 gap-4 @md:grid-cols-2 @2xl:grid-cols-3">
                <QuillSurveyAppearanceInput
                    value={appearance.backgroundColor}
                    onChange={(backgroundColor) => onAppearanceChange({ backgroundColor })}
                    error={validationErrors?.backgroundColor}
                    disabledReason={disabledReason}
                    label="Survey background"
                    inputType="color"
                />
                <QuillSurveyAppearanceInput
                    value={appearance.textColor}
                    onChange={(textColor) => onAppearanceChange({ textColor })}
                    error={validationErrors?.textColor}
                    disabledReason={disabledReason}
                    label="Question text"
                    placeholder="Leave empty for auto-contrast"
                    inputType="color"
                />
                <QuillSurveyAppearanceInput
                    value={appearance.borderColor}
                    onChange={(borderColor) => onAppearanceChange({ borderColor })}
                    error={validationErrors?.borderColor}
                    disabledReason={disabledReason}
                    label="Border"
                    inputType="color"
                />
                <QuillSurveyAppearanceInput
                    value={appearance.inputBackground}
                    onChange={(inputBackground) =>
                        onAppearanceChange({ inputBackground, ratingButtonColor: inputBackground })
                    }
                    error={validationErrors?.inputBackground || validationErrors?.ratingButtonColor}
                    disabledReason={disabledReason}
                    label="Input background"
                    inputType="color"
                />
                <QuillSurveyAppearanceInput
                    value={appearance.inputTextColor}
                    onChange={(inputTextColor) => onAppearanceChange({ inputTextColor })}
                    error={validationErrors?.inputTextColor}
                    disabledReason={disabledReason}
                    label="Input text"
                    placeholder="Leave empty for auto-contrast"
                    inputType="color"
                />
                {customizeRatingButtons && (
                    <QuillSurveyAppearanceInput
                        value={appearance.ratingButtonActiveColor}
                        onChange={(ratingButtonActiveColor) => onAppearanceChange({ ratingButtonActiveColor })}
                        error={validationErrors?.ratingButtonActiveColor}
                        disabledReason={disabledReason}
                        label="Selected rating"
                        inputType="color"
                    />
                )}
                <QuillSurveyAppearanceInput
                    value={appearance.submitButtonColor}
                    onChange={(submitButtonColor) => onAppearanceChange({ submitButtonColor })}
                    error={validationErrors?.submitButtonColor}
                    disabledReason={disabledReason}
                    label="Button background"
                    inputType="color"
                />
                <QuillSurveyAppearanceInput
                    value={appearance.submitButtonTextColor}
                    onChange={(submitButtonTextColor) => onAppearanceChange({ submitButtonTextColor })}
                    error={validationErrors?.submitButtonTextColor}
                    disabledReason={disabledReason}
                    label="Button text"
                    placeholder="Leave empty for auto-contrast"
                    inputType="color"
                />
                {customizePlaceholderText && (
                    <QuillSurveyAppearanceInput
                        value={appearance.placeholder}
                        onChange={(placeholder) => onAppearanceChange({ placeholder })}
                        error={validationErrors?.placeholder}
                        disabledReason={disabledReason}
                        label="Placeholder text"
                    />
                )}
            </div>
        </div>
    )
}
