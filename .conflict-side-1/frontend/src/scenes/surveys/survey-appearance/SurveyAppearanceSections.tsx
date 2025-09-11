import { useValues } from 'kea'
import { DeepPartialMap, ValidationErrorType } from 'kea-forms'

import { IconCheck } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { WEB_SAFE_FONTS } from 'scenes/surveys/constants'
import { surveysLogic } from 'scenes/surveys/surveysLogic'

import { SurveyAppearance, SurveyPosition, SurveyType, SurveyWidgetType } from '~/types'

import { SurveyPositionSelector } from './SurveyAppearancePositionSelector'

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

function SurveyOptionsGroup({
    children,
    sectionTitle,
}: {
    children: React.ReactNode
    sectionTitle: string
}): JSX.Element {
    return (
        <div className="grid grid-cols-2 gap-2 items-start">
            <h3 className="col-span-2 mb-0">{sectionTitle}</h3>
            {children}
        </div>
    )
}

interface SurveyAppearanceInputProps {
    value?: string
    onChange: (value: string) => void
    error?: string
    label: string
    info?: string
}

function SurveyAppearanceInput({ value, onChange, error, label, info }: SurveyAppearanceInputProps): JSX.Element {
    const { surveysStylingAvailable } = useValues(surveysLogic)

    return (
        <LemonField.Pure label={label} className="flex-1 gap-1" info={info}>
            <LemonInput
                value={value}
                onChange={onChange}
                disabled={!surveysStylingAvailable}
                className={IGNORE_ERROR_BORDER_CLASS}
            />
            {error && <LemonField.Error error={error} />}
        </LemonField.Pure>
    )
}

export function SurveyContainerAppearance({
    appearance,
    onAppearanceChange,
    validationErrors,
    surveyType,
}: CommonProps): JSX.Element | null {
    const { surveysStylingAvailable } = useValues(surveysLogic)

    return (
        <SurveyOptionsGroup sectionTitle="Container options">
            <span className="col-span-2 text-secondary">
                These options are only applied in the web surveys. Not on native mobile apps.
            </span>
            <SurveyAppearanceInput
                value={appearance.maxWidth}
                onChange={(maxWidth) => onAppearanceChange({ maxWidth })}
                error={validationErrors?.maxWidth}
                label="Survey width"
                info="Min-width is always set to 300px"
            />
            <SurveyAppearanceInput
                value={appearance.boxPadding}
                onChange={(boxPadding) => onAppearanceChange({ boxPadding })}
                error={validationErrors?.boxPadding}
                label="Box padding"
            />
            <SurveyAppearanceInput
                value={appearance.boxShadow}
                onChange={(boxShadow) => onAppearanceChange({ boxShadow })}
                error={validationErrors?.boxShadow}
                label="Box shadow"
            />
            <SurveyAppearanceInput
                value={appearance.borderRadius}
                onChange={(borderRadius) => onAppearanceChange({ borderRadius })}
                error={validationErrors?.borderRadius}
                label="Border radius"
            />
            <LemonField.Pure
                label="Position"
                info={
                    surveyType === SurveyType.Widget && appearance.widgetType === SurveyWidgetType.Selector
                        ? 'The "next to feedback button" option requires posthog.js version 1.235.2 or higher.'
                        : undefined
                }
                className="gap-1 col-span-2"
            >
                <div className="flex items-center gap-2">
                    <SurveyPositionSelector
                        currentPosition={appearance.position}
                        onAppearanceChange={onAppearanceChange}
                        disabled={!surveysStylingAvailable}
                    />
                    <LemonSelect
                        value={appearance.position}
                        onChange={(position) => onAppearanceChange({ position })}
                        options={gridPositions.map((position) => ({
                            label: positionDisplayNames[position],
                            value: position,
                        }))}
                        disabled={!surveysStylingAvailable}
                    />
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
                    onChange={(fontFamily) => onAppearanceChange({ fontFamily })}
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
            <SurveyAppearanceInput
                value={appearance.zIndex}
                onChange={(zIndex) => onAppearanceChange({ zIndex })}
                error={validationErrors?.zIndex}
                label="Survey form zIndex"
                info="If the survey popup is hidden, set this value higher than the overlapping element's zIndex."
            />
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
    return (
        <SurveyOptionsGroup sectionTitle="Colors and placeholder customization">
            <SurveyAppearanceInput
                value={appearance.backgroundColor}
                onChange={(backgroundColor) => onAppearanceChange({ backgroundColor })}
                error={validationErrors?.backgroundColor}
                label="Background color"
            />
            <SurveyAppearanceInput
                value={appearance.borderColor}
                onChange={(borderColor) => onAppearanceChange({ borderColor })}
                error={validationErrors?.borderColor}
                label="Border color"
            />
            <SurveyAppearanceInput
                value={appearance.submitButtonColor}
                onChange={(submitButtonColor) => onAppearanceChange({ submitButtonColor })}
                error={validationErrors?.submitButtonColor}
                label="Button color"
            />
            <SurveyAppearanceInput
                value={appearance.submitButtonTextColor}
                onChange={(submitButtonTextColor) => onAppearanceChange({ submitButtonTextColor })}
                error={validationErrors?.submitButtonTextColor}
                label="Button text color"
            />
            {customizeRatingButtons && (
                <>
                    <SurveyAppearanceInput
                        value={appearance.ratingButtonColor}
                        onChange={(ratingButtonColor) => onAppearanceChange({ ratingButtonColor })}
                        error={validationErrors?.ratingButtonColor}
                        label="Rating button color"
                    />
                    <SurveyAppearanceInput
                        value={appearance.ratingButtonActiveColor}
                        onChange={(ratingButtonActiveColor) => onAppearanceChange({ ratingButtonActiveColor })}
                        error={validationErrors?.ratingButtonActiveColor}
                        label="Rating button active color"
                    />
                </>
            )}
            {customizePlaceholderText && (
                <SurveyAppearanceInput
                    value={appearance.placeholder}
                    onChange={(placeholder) => onAppearanceChange({ placeholder })}
                    error={validationErrors?.placeholder}
                    label="Placeholder text"
                />
            )}
        </SurveyOptionsGroup>
    )
}
