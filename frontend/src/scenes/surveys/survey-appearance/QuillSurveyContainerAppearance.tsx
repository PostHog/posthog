import { useValues } from 'kea'
import { DeepPartialMap, ValidationErrorType } from 'kea-forms'
import { useId } from 'react'

import { IconCheck } from '@posthog/icons'
import {
    Button,
    Field,
    FieldDescription,
    FieldLabel,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@posthog/quill'

import { WEB_SAFE_FONTS } from 'scenes/surveys/constants'
import { surveysLogic } from 'scenes/surveys/surveysLogic'

import { SurveyAppearance, SurveyPosition, SurveyType, SurveyWidgetType } from '~/types'

import { QuillSurveyAppearanceInput } from './QuillSurveyAppearanceInput'
import { SurveyPositionSelector } from './SurveyAppearancePositionSelector'
import { gridPositions, positionDisplayNames } from './SurveyAppearanceSections'

export function QuillSurveyContainerAppearance({
    appearance,
    onAppearanceChange,
    validationErrors,
    surveyType,
    disabledReason,
}: {
    appearance: SurveyAppearance
    onAppearanceChange: (appearance: SurveyAppearance) => void
    validationErrors?: DeepPartialMap<SurveyAppearance, ValidationErrorType> | null
    surveyType?: SurveyType
    disabledReason?: string
}): JSX.Element {
    const { surveysStylingAvailable } = useValues(surveysLogic)
    const fontId = useId()
    const positionId = useId()

    const disabled = !surveysStylingAvailable || !!disabledReason
    const showsNextToTrigger = surveyType === SurveyType.Widget && appearance.widgetType === SurveyWidgetType.Selector

    return (
        <div className="flex flex-col gap-4">
            <div className="@container">
                <div className="grid grid-cols-1 gap-4 @md:grid-cols-2">
                    <QuillSurveyAppearanceInput
                        value={appearance.maxWidth}
                        onChange={(maxWidth) => onAppearanceChange({ maxWidth })}
                        error={validationErrors?.maxWidth}
                        disabledReason={disabledReason}
                        label="Survey width"
                        info="Min-width is always set to 300px"
                    />
                    <QuillSurveyAppearanceInput
                        value={appearance.boxPadding}
                        onChange={(boxPadding) => onAppearanceChange({ boxPadding })}
                        error={validationErrors?.boxPadding}
                        disabledReason={disabledReason}
                        label="Box padding"
                    />
                    <QuillSurveyAppearanceInput
                        value={appearance.borderRadius}
                        onChange={(borderRadius) => onAppearanceChange({ borderRadius })}
                        error={validationErrors?.borderRadius}
                        disabledReason={disabledReason}
                        label="Border radius"
                    />
                    <QuillSurveyAppearanceInput
                        value={appearance.boxShadow}
                        onChange={(boxShadow) => onAppearanceChange({ boxShadow })}
                        error={validationErrors?.boxShadow}
                        disabledReason={disabledReason}
                        label="Box shadow"
                    />
                    <Field>
                        <FieldLabel htmlFor={fontId}>Font family</FieldLabel>
                        <Select
                            value={appearance?.fontFamily}
                            onValueChange={(fontFamily) =>
                                onAppearanceChange({ fontFamily: fontFamily as SurveyAppearance['fontFamily'] })
                            }
                            disabled={disabled}
                        >
                            <SelectTrigger id={fontId} disabledReason={disabledReason}>
                                <SelectValue>
                                    {(value: string) =>
                                        WEB_SAFE_FONTS.find((font) => font.value === value)?.label ?? value
                                    }
                                </SelectValue>
                            </SelectTrigger>
                            <SelectContent>
                                {WEB_SAFE_FONTS.map((font) => (
                                    <SelectItem key={font.value} value={font.value}>
                                        <span className={font.value.toLowerCase().replace(/\s/g, '-')}>
                                            {font.label}
                                        </span>
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                        <FieldDescription>
                            Custom font selection requires at least posthog-js 1.223.4, posthog-ios 4.0.6,
                            posthog-android-surveys-compose 1.1.0, or posthog_flutter 5.56.0
                        </FieldDescription>
                    </Field>
                    <QuillSurveyAppearanceInput
                        value={appearance.zIndex}
                        onChange={(zIndex) => onAppearanceChange({ zIndex })}
                        error={validationErrors?.zIndex}
                        disabledReason={disabledReason}
                        label="z-index"
                        info="If the survey popup is hidden, set this value higher than the overlapping element's zIndex."
                    />
                </div>
            </div>

            <Field>
                <FieldLabel htmlFor={positionId}>Position</FieldLabel>
                <div className="flex flex-wrap items-center gap-2">
                    <SurveyPositionSelector
                        currentPosition={appearance.position}
                        onAppearanceChange={onAppearanceChange}
                        disabled={disabled}
                    />
                    <Select
                        value={appearance.position}
                        onValueChange={(position) => onAppearanceChange({ position: position as SurveyPosition })}
                        disabled={disabled}
                    >
                        <SelectTrigger id={positionId} disabledReason={disabledReason}>
                            <SelectValue>
                                {(value: SurveyPosition) => (value ? positionDisplayNames[value] : null)}
                            </SelectValue>
                        </SelectTrigger>
                        <SelectContent>
                            {gridPositions.map((position) => (
                                <SelectItem key={position} value={position}>
                                    {positionDisplayNames[position]}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </div>
                {showsNextToTrigger && (
                    <div>
                        <Button
                            variant="outline"
                            aria-pressed={appearance.position === SurveyPosition.NextToTrigger}
                            onClick={() =>
                                onAppearanceChange({ ...appearance, position: SurveyPosition.NextToTrigger })
                            }
                            disabled={disabled}
                            disabledReason={disabledReason}
                        >
                            {positionDisplayNames[SurveyPosition.NextToTrigger]}
                            {appearance.position === SurveyPosition.NextToTrigger && <IconCheck />}
                        </Button>
                    </div>
                )}
                {showsNextToTrigger && (
                    <FieldDescription>
                        The "next to feedback button" option requires posthog.js version 1.235.2 or higher.
                    </FieldDescription>
                )}
            </Field>
        </div>
    )
}
