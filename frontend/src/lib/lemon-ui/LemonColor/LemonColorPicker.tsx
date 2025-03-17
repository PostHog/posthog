import { LemonColorGlyph, LemonInput, LemonLabel, Popover } from '@posthog/lemon-ui'
import { useState } from 'react'

import { LemonColorButton } from './LemonColorButton'
import { LemonColorList } from './LemonColorList'

const colorTokens = Array.from({ length: 15 }, (_, i) => `preset-${i + 1}`)

type LemonColorPickerProps = {
    onColorChange: (color: string) => void
    showCustomColor?: boolean
    hideDropdown?: boolean
}

export const LemonColorPickerOverlay = ({
    showCustomColor: allowCustomColor = false,
}: Omit<LemonColorPickerProps, 'hideDropdown'>): JSX.Element => {
    const [color, setColor] = useState('#ff0000')

    return (
        <div className="w-52 flex flex-col p-2">
            <LemonLabel className="mt-1 mb-0.5">Preset colors</LemonLabel>
            <LemonColorList
                colorTokens={colorTokens.slice(0, 11)}
                selectedColorToken={colorTokens[3]}
                onClick={(colorToken) => {
                    alert(colorToken)
                }}
            />
            {allowCustomColor && (
                <div>
                    <LemonLabel className="mt-2 mb-0.5">Custom color</LemonLabel>
                    <div className="flex items-center gap-2">
                        <LemonColorGlyph color="#ff0000" className="ml-1.5" />
                        <LemonInput
                            className="mt-1 font-mono"
                            // label="Color"
                            size="small"
                            value={color}
                            onChange={(e) => setColor(e.target.value)}
                            // prefix={}
                        />
                    </div>
                </div>
            )}
        </div>
    )
}

export const LemonColorPicker = ({ hideDropdown = false, ...props }: LemonColorPickerProps): JSX.Element => {
    const [isOpen, setIsOpen] = useState(false)

    return (
        <Popover
            visible={isOpen}
            overlay={<LemonColorPickerOverlay {...props} />}
            onClickOutside={() => setIsOpen(false)}
        >
            <div className="relative">
                <LemonColorButton
                    type="secondary"
                    onClick={() => setIsOpen(!isOpen)}
                    sideIcon={hideDropdown ? null : undefined}
                />
            </div>
        </Popover>
    )
}
