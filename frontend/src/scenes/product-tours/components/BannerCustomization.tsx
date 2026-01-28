import { ProductTourAppearance, ProductTourStep } from '~/types'

import { BoxShadowSelector, ColorPickerField, FontSelector } from './CustomizationFields'
import { BannerPreviewWrapper } from './ProductTourPreview'

const DEFAULT_BANNER_APPEARANCE: ProductTourAppearance = {
    backgroundColor: '#ffffff',
    textColor: '#1d1f27',
    borderColor: '#e5e7eb',
    fontFamily: 'system-ui',
    boxShadow: '0 2px 8px rgba(0, 0, 0, 0.1)',
}

interface BannerCustomizationProps {
    appearance: ProductTourAppearance | undefined
    step: ProductTourStep | undefined
    onChange: (appearance: ProductTourAppearance) => void
}

export function BannerCustomization({ appearance, step, onChange }: BannerCustomizationProps): JSX.Element {
    const currentAppearance = { ...DEFAULT_BANNER_APPEARANCE, ...appearance }

    const updateAppearance = (updates: Partial<ProductTourAppearance>): void => {
        onChange({ ...currentAppearance, ...updates })
    }

    return (
        <div className="space-y-6">
            {step && <BannerPreviewWrapper step={step} appearance={currentAppearance} />}

            <div className="flex gap-8">
                <div className="flex-1 space-y-4">
                    <h3 className="font-semibold">Colors</h3>
                    <div className="grid grid-cols-3 gap-4">
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
                            label="Border"
                            value={currentAppearance.borderColor}
                            onChange={(borderColor) => updateAppearance({ borderColor })}
                            showNone
                        />
                    </div>
                </div>

                <div className="flex-1 space-y-4">
                    <h3 className="font-semibold">Style</h3>
                    <div className="grid grid-cols-2 gap-4">
                        <FontSelector
                            value={currentAppearance.fontFamily}
                            onChange={(fontFamily) => updateAppearance({ fontFamily })}
                        />
                        <BoxShadowSelector
                            value={currentAppearance.boxShadow}
                            onChange={(boxShadow) => updateAppearance({ boxShadow })}
                        />
                    </div>
                </div>
            </div>
        </div>
    )
}
