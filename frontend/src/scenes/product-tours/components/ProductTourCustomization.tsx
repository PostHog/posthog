import { useState } from 'react'

import { LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider/LemonSlider'

import { ProductTourAppearance, ProductTourStep } from '~/types'

import { BoxShadowSelector, ColorPickerField, FontSelector } from './CustomizationFields'
import { ProductTourPreview } from './ProductTourPreview'

const DEFAULT_APPEARANCE: ProductTourAppearance = {
    backgroundColor: '#ffffff',
    textColor: '#1d1f27',
    buttonColor: '#1d1f27',
    borderRadius: 8,
    buttonBorderRadius: 6,
    borderColor: '#e5e7eb',
    fontFamily: 'system-ui',
    boxShadow: '0 4px 12px rgba(0, 0, 0, 0.15)',
    showOverlay: true,
    whiteLabel: false,
}

interface ProductTourCustomizationProps {
    appearance: ProductTourAppearance | undefined
    steps: ProductTourStep[]
    onChange: (appearance: ProductTourAppearance) => void
}

function TourStepPreview({
    appearance,
    steps,
    selectedStepIndex,
    onStepChange,
}: {
    appearance: ProductTourAppearance
    steps: ProductTourStep[]
    selectedStepIndex: number
    onStepChange: (index: number) => void
}): JSX.Element {
    const step = steps[selectedStepIndex]

    const stepOptions = steps.map((_, index) => ({
        label: `Step ${index + 1}`,
        value: index,
    }))

    return (
        <div className="border rounded-lg p-4 bg-surface-alt">
            <div className="flex items-center justify-between mb-3">
                <h4 className="font-semibold text-sm">Preview</h4>
                {steps.length > 1 && (
                    <LemonSelect
                        size="small"
                        value={selectedStepIndex}
                        onChange={(value) => onStepChange(value ?? 0)}
                        options={stepOptions}
                    />
                )}
            </div>
            <div className="flex justify-center p-8 bg-[#f0f0f0] rounded min-h-[200px]">
                {step && (
                    <ProductTourPreview
                        step={step}
                        appearance={appearance}
                        stepIndex={selectedStepIndex}
                        totalSteps={steps.length}
                    />
                )}
            </div>
        </div>
    )
}

export function ProductTourCustomization({ appearance, steps, onChange }: ProductTourCustomizationProps): JSX.Element {
    const [selectedStepIndex, setSelectedStepIndex] = useState(0)
    const currentAppearance = { ...DEFAULT_APPEARANCE, ...appearance }

    const updateAppearance = (updates: Partial<ProductTourAppearance>): void => {
        onChange({ ...currentAppearance, ...updates })
    }

    return (
        <div className="flex gap-6">
            <div className="flex-1 space-y-6 max-w-xl">
                <div>
                    <h3 className="font-semibold mb-4">Colors</h3>
                    <div className="grid grid-cols-2 gap-4">
                        <ColorPickerField
                            label="Background"
                            value={currentAppearance.backgroundColor}
                            onChange={(backgroundColor) => updateAppearance({ backgroundColor })}
                        />
                        <ColorPickerField
                            label="Text"
                            value={currentAppearance.textColor}
                            onChange={(textColor) => updateAppearance({ textColor })}
                        />
                        <ColorPickerField
                            label="Button"
                            value={currentAppearance.buttonColor}
                            onChange={(buttonColor) => updateAppearance({ buttonColor })}
                        />
                        <ColorPickerField
                            label="Border"
                            value={currentAppearance.borderColor}
                            onChange={(borderColor) => updateAppearance({ borderColor })}
                        />
                    </div>
                </div>

                <div>
                    <h3 className="font-semibold mb-4">Style</h3>
                    <div className="space-y-4">
                        <LemonField.Pure label="Border radius">
                            <div className="flex items-center gap-3">
                                <LemonSlider
                                    className="flex-1"
                                    value={currentAppearance.borderRadius}
                                    onChange={(borderRadius) => updateAppearance({ borderRadius })}
                                    min={0}
                                    max={24}
                                    step={1}
                                />
                                <span className="text-sm text-secondary w-12 text-right">
                                    {currentAppearance.borderRadius}px
                                </span>
                            </div>
                        </LemonField.Pure>

                        <LemonField.Pure label="Button border radius">
                            <div className="flex items-center gap-3">
                                <LemonSlider
                                    className="flex-1"
                                    value={currentAppearance.buttonBorderRadius}
                                    onChange={(buttonBorderRadius) => updateAppearance({ buttonBorderRadius })}
                                    min={0}
                                    max={24}
                                    step={1}
                                />
                                <span className="text-sm text-secondary w-12 text-right">
                                    {currentAppearance.buttonBorderRadius}px
                                </span>
                            </div>
                        </LemonField.Pure>

                        <FontSelector
                            value={currentAppearance.fontFamily}
                            onChange={(fontFamily) => updateAppearance({ fontFamily })}
                        />

                        <BoxShadowSelector
                            value={currentAppearance.boxShadow}
                            onChange={(boxShadow) => updateAppearance({ boxShadow })}
                        />

                        <div className="flex items-center justify-between">
                            <span className="text-sm font-medium">Show dark overlay</span>
                            <LemonSwitch
                                checked={currentAppearance.showOverlay ?? true}
                                onChange={(showOverlay) => updateAppearance({ showOverlay })}
                            />
                        </div>
                    </div>
                </div>

                <div>
                    <h3 className="font-semibold mb-4">Branding</h3>
                    <div className="flex items-center justify-between p-3 border rounded bg-surface-primary">
                        <div>
                            <div className="font-medium">Remove PostHog branding</div>
                        </div>
                        <LemonSwitch
                            checked={!!currentAppearance.whiteLabel}
                            onChange={(whiteLabel) => updateAppearance({ whiteLabel })}
                        />
                    </div>
                </div>
            </div>

            <div className="flex-1">
                <TourStepPreview
                    appearance={currentAppearance}
                    steps={steps}
                    selectedStepIndex={selectedStepIndex}
                    onStepChange={setSelectedStepIndex}
                />
            </div>
        </div>
    )
}
