import { IconCheck } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useValues } from 'kea'
import { DeepPartialMap, ValidationErrorType } from 'kea-forms'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { defaultSurveyAppearance, WEB_SAFE_FONTS } from 'scenes/surveys/constants'
import { SurveyOptionsGroup } from 'scenes/surveys/survey-form/SurveyOptionsGroup'
import { surveysLogic } from 'scenes/surveys/surveysLogic'

import { SurveyAppearance, SurveyPosition, SurveyType, SurveyWidgetType } from '~/types'

interface CommonProps {
    appearance: SurveyAppearance
    onAppearanceChange: (appearance: SurveyAppearance) => void
    validationErrors?: DeepPartialMap<SurveyAppearance, ValidationErrorType> | null
    surveyType?: SurveyType
}

const gridPositions: SurveyPosition[] = [
    SurveyPosition.TopLeft,
    SurveyPosition.TopCenter,
    SurveyPosition.TopRight,
    SurveyPosition.MiddleLeft,
    SurveyPosition.MiddleCenter,
    SurveyPosition.MiddleRight,
    SurveyPosition.Left,
    SurveyPosition.Center,
    SurveyPosition.Right,
    // Bottom positions are not in the current enum, will add if they become available
    // SurveyPosition.BottomLeft, SurveyPosition.BottomCenter, SurveyPosition.BottomRight
]

const positionDisplayNames: Record<SurveyPosition, string> = {
    [SurveyPosition.TopLeft]: 'Top Left',
    [SurveyPosition.TopCenter]: 'Top Center',
    [SurveyPosition.TopRight]: 'Top Right',
    [SurveyPosition.MiddleLeft]: 'Middle Left',
    [SurveyPosition.MiddleCenter]: 'Middle Center',
    [SurveyPosition.MiddleRight]: 'Middle Right',
    [SurveyPosition.Left]: 'Bottom Left',
    [SurveyPosition.Center]: 'Bottom Center',
    [SurveyPosition.Right]: 'Bottom Right',
    [SurveyPosition.NextToTrigger]: 'Next to feedback button',
}

const IGNORE_ERROR_BORDER_CLASS = 'ignore-error-border'

export function SurveyContainerAppearance({
    appearance,
    onAppearanceChange,
    validationErrors,
    surveyType,
}: CommonProps): JSX.Element {
    const { surveysStylingAvailable } = useValues(surveysLogic)

    return (
        <SurveyOptionsGroup sectionTitle="Container options">
            <span className="col-span-2 text-secondary">
                These options are only applied in the web surveys. Not on native mobile apps.
            </span>
            <LemonField.Pure label="Max width" className="flex-1 gap-1">
                <LemonInput
                    value={appearance.maxWidth}
                    onChange={(maxWidth) => onAppearanceChange({ ...appearance, maxWidth })}
                    disabled={!surveysStylingAvailable}
                    className={IGNORE_ERROR_BORDER_CLASS}
                />
            </LemonField.Pure>
            <LemonField.Pure label="Box padding" className="flex-1 gap-1">
                <LemonInput
                    value={appearance.boxPadding}
                    onChange={(boxPadding) => onAppearanceChange({ ...appearance, boxPadding })}
                    disabled={!surveysStylingAvailable}
                    className={clsx(validationErrors?.boxPadding ? 'border-danger' : IGNORE_ERROR_BORDER_CLASS)}
                />
                {validationErrors?.boxPadding && <LemonField.Error error={validationErrors?.boxPadding} />}
            </LemonField.Pure>
            <LemonField.Pure label="Box shadow" className="flex-1 gap-1">
                <LemonInput
                    value={appearance.boxShadow}
                    onChange={(boxShadow) => onAppearanceChange({ ...appearance, boxShadow })}
                    disabled={!surveysStylingAvailable}
                />
            </LemonField.Pure>
            <LemonField.Pure label="Border radius" className="flex-1 gap-1">
                <LemonInput
                    value={appearance.borderRadius || defaultSurveyAppearance.borderRadius}
                    onChange={(borderRadius) => onAppearanceChange({ ...appearance, borderRadius })}
                    disabled={!surveysStylingAvailable}
                    className={clsx(validationErrors?.borderRadius ? 'border-danger' : IGNORE_ERROR_BORDER_CLASS)}
                />
                {validationErrors?.borderRadius && <LemonField.Error error={validationErrors?.borderRadius} />}
            </LemonField.Pure>

            <LemonField.Pure
                label="Position"
                info={
                    surveyType === SurveyType.Widget && appearance.widgetType === SurveyWidgetType.Selector
                        ? 'The "next to feedback button" option requires posthog.js version 1.235.2 or higher.'
                        : undefined
                }
                className="gap-1 col-span-2"
            >
                <div className="grid grid-cols-3 gap-1 mb-1">
                    {gridPositions.map((position) => (
                        <LemonButton
                            key={position}
                            type="tertiary"
                            size="small"
                            onClick={() => onAppearanceChange({ ...appearance, position })}
                            active={appearance.position === position}
                            disabled={!surveysStylingAvailable}
                            className="justify-center text-xs" // Ensure text is centered and button is small
                        >
                            {positionDisplayNames[position]}
                            {appearance.position === position && <IconCheck className="ml-2 size-4" />}
                        </LemonButton>
                    ))}
                </div>
                {surveyType === SurveyType.Widget && appearance.widgetType === SurveyWidgetType.Selector && (
                    <div className="flex flex-col gap-1 items-start w-60">
                        <LemonButton
                            key={SurveyPosition.NextToTrigger}
                            type="tertiary"
                            size="small"
                            fullWidth
                            onClick={() =>
                                onAppearanceChange({ ...appearance, position: SurveyPosition.NextToTrigger })
                            }
                            active={appearance.position === SurveyPosition.NextToTrigger}
                            disabled={!surveysStylingAvailable}
                        >
                            {positionDisplayNames[SurveyPosition.NextToTrigger]}
                            {appearance.position === SurveyPosition.NextToTrigger && (
                                <IconCheck className="ml-2 size-4" />
                            )}
                        </LemonButton>
                    </div>
                )}
            </LemonField.Pure>
            <LemonField.Pure
                label="Font family"
                info="Custom font selection requires at least version 1.223.4 of posthog-js"
                className="gap-1"
            >
                <LemonSelect
                    value={appearance?.fontFamily}
                    onChange={(fontFamily) => onAppearanceChange({ ...appearance, fontFamily })}
                    options={WEB_SAFE_FONTS.map((font) => {
                        return {
                            label: <span className={font.value.toLowerCase().replace(/\s/g, '-')}>{font.label}</span>,
                            value: font.value,
                        }
                    })}
                    className="ignore-error-border"
                    disabled={!surveysStylingAvailable}
                />
            </LemonField.Pure>
            <LemonField.Pure
                label="Survey form zIndex"
                info="If the survey popup is hidden, set this value higher than the overlapping element's zIndex."
                className="gap-1"
            >
                <LemonInput
                    type="number"
                    value={appearance.zIndex !== undefined ? Number(appearance.zIndex) : undefined}
                    onChange={(val) =>
                        onAppearanceChange({ ...appearance, zIndex: val === undefined ? undefined : String(val) })
                    }
                    disabled={!surveysStylingAvailable}
                    placeholder="e.g. 2147482647"
                    className={IGNORE_ERROR_BORDER_CLASS}
                />
            </LemonField.Pure>
        </SurveyOptionsGroup>
    )
}

export function SurveyColorsAppearance({
    appearance,
    onAppearanceChange,
    validationErrors,
    customizeRatingButtons,
    customizePlaceholderText,
}: CommonProps & {
    customizeRatingButtons: boolean
    customizePlaceholderText: boolean
}): JSX.Element {
    const { surveysStylingAvailable } = useValues(surveysLogic)
    return (
        <SurveyOptionsGroup sectionTitle="Colors and placeholder customization">
            <LemonField.Pure label="Background color" className="flex-1 gap-1">
                <LemonInput
                    value={appearance.backgroundColor}
                    onChange={(backgroundColor) => onAppearanceChange({ ...appearance, backgroundColor })}
                    disabled={!surveysStylingAvailable}
                    className={clsx(validationErrors?.backgroundColor ? 'border-danger' : IGNORE_ERROR_BORDER_CLASS)}
                />
                {validationErrors?.backgroundColor && <LemonField.Error error={validationErrors?.backgroundColor} />}
            </LemonField.Pure>
            <LemonField.Pure label="Border color" className="flex-1 gap-1">
                <LemonInput
                    value={appearance.borderColor}
                    onChange={(borderColor) => onAppearanceChange({ ...appearance, borderColor })}
                    disabled={!surveysStylingAvailable}
                    className={clsx(validationErrors?.borderColor ? 'border-danger' : IGNORE_ERROR_BORDER_CLASS)}
                />
                {validationErrors?.borderColor && <LemonField.Error error={validationErrors?.borderColor} />}
            </LemonField.Pure>
            <LemonField.Pure label="Button color" className="flex-1 gap-1">
                <LemonInput
                    value={appearance.submitButtonColor}
                    onChange={(submitButtonColor) => onAppearanceChange({ ...appearance, submitButtonColor })}
                    disabled={!surveysStylingAvailable}
                    className={clsx(validationErrors?.submitButtonColor ? 'border-danger' : IGNORE_ERROR_BORDER_CLASS)}
                />
                {validationErrors?.submitButtonColor && (
                    <LemonField.Error error={validationErrors?.submitButtonColor} />
                )}
            </LemonField.Pure>
            <LemonField.Pure label="Button text color" className="flex-1 gap-1">
                <LemonInput
                    value={appearance.submitButtonTextColor}
                    onChange={(submitButtonTextColor) => onAppearanceChange({ ...appearance, submitButtonTextColor })}
                    disabled={!surveysStylingAvailable}
                    className={clsx(
                        validationErrors?.submitButtonTextColor ? 'border-danger' : IGNORE_ERROR_BORDER_CLASS
                    )}
                />
                {validationErrors?.submitButtonTextColor && (
                    <LemonField.Error error={validationErrors?.submitButtonTextColor} />
                )}
            </LemonField.Pure>
            {customizeRatingButtons && (
                <>
                    <LemonField.Pure label="Rating button color" className="flex-1 gap-1">
                        <LemonInput
                            value={appearance.ratingButtonColor}
                            onChange={(ratingButtonColor) => onAppearanceChange({ ...appearance, ratingButtonColor })}
                            disabled={!surveysStylingAvailable}
                            className={clsx(
                                validationErrors?.ratingButtonColor ? 'border-danger' : IGNORE_ERROR_BORDER_CLASS
                            )}
                        />
                        {validationErrors?.ratingButtonColor && (
                            <LemonField.Error error={validationErrors?.ratingButtonColor} />
                        )}
                    </LemonField.Pure>
                    <LemonField.Pure label="Rating button active color" className="flex-1 gap-1">
                        <LemonInput
                            value={appearance.ratingButtonActiveColor}
                            onChange={(ratingButtonActiveColor) =>
                                onAppearanceChange({ ...appearance, ratingButtonActiveColor })
                            }
                            disabled={!surveysStylingAvailable}
                            className={clsx(
                                validationErrors?.ratingButtonActiveColor ? 'border-danger' : IGNORE_ERROR_BORDER_CLASS
                            )}
                        />
                        {validationErrors?.ratingButtonActiveColor && (
                            <LemonField.Error error={validationErrors?.ratingButtonActiveColor} />
                        )}
                    </LemonField.Pure>
                </>
            )}
            {customizePlaceholderText && (
                <LemonField.Pure label="Placeholder text" className="gap-1">
                    <LemonInput
                        value={appearance.placeholder}
                        onChange={(placeholder) => onAppearanceChange({ ...appearance, placeholder })}
                        disabled={!surveysStylingAvailable}
                        className={IGNORE_ERROR_BORDER_CLASS}
                    />
                </LemonField.Pure>
            )}
        </SurveyOptionsGroup>
    )
}
