import { LemonColorGlyph, LemonInput, LemonLabel, Popover } from '@posthog/lemon-ui'
import { DataColorToken } from 'lib/colors'
import { useEffect, useState } from 'react'

import { LemonColorButton } from './LemonColorButton'
import { LemonColorList } from './LemonColorList'

type LemonColorPickerProps = {
    themeId?: number
    colors?: string[]
    colorTokens?: DataColorToken[]
    selectedColor?: string | null
    selectedColorToken?: DataColorToken | null
    onSelectColor?: (color: string) => void
    onSelectColorToken?: (colorToken: DataColorToken) => void
    showCustomColor?: boolean
    hideDropdown?: boolean
}

export const LemonColorPickerOverlay = ({
    themeId,
    colors,
    colorTokens,
    selectedColor,
    selectedColorToken,
    onSelectColor,
    onSelectColorToken,
    showCustomColor = false,
}: Omit<LemonColorPickerProps, 'hideDropdown'>): JSX.Element => {
    const [color, setColor] = useState(selectedColor || null)
    const [lastValidColor, setLastValidColor] = useState<string>('#000000')

    useEffect(() => {
        // allow only 6-digit hex colors
        // other color formats are not supported everywhere e.g. insight visualizations
        if (showCustomColor && color != null && /^#[0-9A-Fa-f]{6}$/.test(color)) {
            setLastValidColor(color)
            onSelectColor?.(color)
        }
    }, [color, showCustomColor, onSelectColor])

    return (
        <div className="w-52 flex flex-col p-2">
            <LemonLabel className="mt-1 mb-0.5">Preset colors</LemonLabel>
            <LemonColorList
                themeId={themeId}
                colors={colors}
                colorTokens={colorTokens}
                selectedColor={selectedColor}
                selectedColorToken={selectedColorToken}
                onClick={colorTokens ? onSelectColorToken : onSelectColor}
            />
            {showCustomColor && (
                <div>
                    <LemonLabel className="mt-2 mb-0.5">Custom color</LemonLabel>
                    <div className="flex items-center gap-2">
                        <LemonColorGlyph color={lastValidColor} className="ml-1.5" />
                        <LemonInput className="mt-1 font-mono" size="small" value={color || ''} onChange={setColor} />
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
                    color={props.selectedColor}
                    colorToken={props.selectedColorToken}
                    onClick={() => setIsOpen(!isOpen)}
                    sideIcon={hideDropdown ? null : undefined}
                />
            </div>
        </Popover>
    )
}
