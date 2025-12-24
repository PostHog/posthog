import { renderProductTourPreview } from 'posthog-js/dist/product-tours-preview'
import { useEffect, useRef, useState } from 'react'

import { LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import { LemonColorPicker } from 'lib/lemon-ui/LemonColor/LemonColorPicker'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider/LemonSlider'
import { WEB_SAFE_FONTS } from 'scenes/surveys/constants'

import { ProductTourAppearance, ProductTourStep } from '~/types'

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

const COLOR_PRESETS = [
    '#ffffff',
    '#1d1f27',
    '#1d4aff',
    '#f3f4f6',
    '#e5e7eb',
    '#ef4444',
    '#22c55e',
    '#f59e0b',
    '#8b5cf6',
    '#ec4899',
]

const BOX_SHADOW_PRESETS = [
    { value: 'none', label: 'None' },
    { value: '0 2px 8px rgba(0, 0, 0, 0.1)', label: 'Subtle' },
    { value: '0 4px 12px rgba(0, 0, 0, 0.15)', label: 'Medium' },
    { value: '0 8px 24px rgba(0, 0, 0, 0.2)', label: 'Large' },
    { value: '0 12px 32px rgba(0, 0, 0, 0.25)', label: 'Extra large' },
]

interface ProductTourCustomizationProps {
    appearance: ProductTourAppearance | undefined
    steps: ProductTourStep[]
    onChange: (appearance: ProductTourAppearance) => void
}

function ColorPickerField({
    label,
    value,
    onChange,
}: {
    label: string
    value: string | undefined
    onChange: (color: string) => void
}): JSX.Element {
    return (
        <LemonField.Pure label={label} className="flex-1">
            <div className="flex items-center gap-2">
                <LemonColorPicker
                    colors={COLOR_PRESETS}
                    selectedColor={value}
                    onSelectColor={onChange}
                    showCustomColor
                />
                <span className="text-xs text-secondary font-mono">{value}</span>
            </div>
        </LemonField.Pure>
    )
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
    const previewRef = useRef<HTMLDivElement>(null)
    const step = steps[selectedStepIndex]

    useEffect(() => {
        if (previewRef.current && step) {
            renderProductTourPreview({
                step: step as any, // will update this when things settle down
                appearance: appearance as any,
                parentElement: previewRef.current,
                stepIndex: selectedStepIndex,
                totalSteps: steps.length,
            })
        }
    }, [step, appearance, selectedStepIndex, steps.length])

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
                <div ref={previewRef} />
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

                        <LemonField.Pure label="Font">
                            <LemonSelect
                                value={currentAppearance.fontFamily}
                                onChange={(fontFamily) => updateAppearance({ fontFamily: fontFamily || 'system-ui' })}
                                options={WEB_SAFE_FONTS.map((font) => ({
                                    label: (
                                        <span style={{ fontFamily: font.value === 'inherit' ? undefined : font.value }}>
                                            {font.label}
                                        </span>
                                    ),
                                    value: font.value,
                                }))}
                            />
                        </LemonField.Pure>

                        <LemonField.Pure label="Drop shadow">
                            <LemonSelect
                                value={currentAppearance.boxShadow}
                                onChange={(boxShadow) =>
                                    updateAppearance({ boxShadow: boxShadow || '0 4px 12px rgba(0, 0, 0, 0.15)' })
                                }
                                options={BOX_SHADOW_PRESETS}
                            />
                        </LemonField.Pure>

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
