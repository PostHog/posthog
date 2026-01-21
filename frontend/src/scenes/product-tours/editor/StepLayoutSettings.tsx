import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { PositionSelector } from 'scenes/surveys/survey-appearance/SurveyAppearancePositionSelector'

import { ProductTourStep, ScreenPosition, SurveyPosition } from '~/types'

import {
    TOUR_STEP_MAX_WIDTH,
    TOUR_STEP_MIN_WIDTH,
    TOUR_WIDTH_PRESET_OPTIONS,
    getWidthValue,
    isPresetWidth,
} from './ProductTourStepsEditor'

export interface StepLayoutSettingsProps {
    step: ProductTourStep
    onChange: (updates: Partial<ProductTourStep>) => void
    showPosition?: boolean
}

export function StepLayoutSettings({ step, onChange, showPosition = true }: StepLayoutSettingsProps): JSX.Element {
    return (
        <div className="flex gap-12 items-start">
            <div className="w-80">
                <label className="text-sm font-medium block mb-2">Width</label>
                <div className="flex items-center gap-3 mb-2">
                    <LemonSlider
                        value={getWidthValue(step.maxWidth)}
                        onChange={(value) => onChange({ maxWidth: value })}
                        min={TOUR_STEP_MIN_WIDTH}
                        max={TOUR_STEP_MAX_WIDTH}
                        step={10}
                        className="flex-1"
                    />
                    <span className="text-sm text-muted w-12 text-right">{getWidthValue(step.maxWidth)}px</span>
                </div>
                <LemonSegmentedButton
                    size="small"
                    value={isPresetWidth(getWidthValue(step.maxWidth)) ? getWidthValue(step.maxWidth) : undefined}
                    onChange={(value) => onChange({ maxWidth: value })}
                    options={TOUR_WIDTH_PRESET_OPTIONS}
                />
            </div>

            {showPosition && (
                <div>
                    <label className="text-sm font-medium block mb-2">Position</label>
                    <PositionSelector
                        value={step.modalPosition ?? SurveyPosition.MiddleCenter}
                        onChange={(position: ScreenPosition) => onChange({ modalPosition: position })}
                    />
                </div>
            )}
        </div>
    )
}
