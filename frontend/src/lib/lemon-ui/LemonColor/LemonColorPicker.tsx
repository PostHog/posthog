import { LemonColorGlyph, LemonInput, LemonLabel, Popover } from '@posthog/lemon-ui'
import { DataColorToken } from 'lib/colors'
import { useState } from 'react'

import { LemonColorButton } from './LemonColorButton'
import { LemonColorList } from './LemonColorList'

type LemonColorPickerBaseProps = {
    showCustomColor?: boolean
    hideDropdown?: boolean
    preventPopoverClose?: boolean
}

type LemonColorPickerColorProps = LemonColorPickerBaseProps & {
    colors: string[]
    selectedColor?: string | null
    onSelectColor: (color: string) => void
    colorTokens?: never
    selectedColorToken?: never
    onSelectColorToken?: never
    themeId?: never
}

type LemonColorPickerTokenProps = LemonColorPickerBaseProps & {
    colorTokens: DataColorToken[]
    selectedColorToken?: DataColorToken | null
    onSelectColorToken: (colorToken: DataColorToken) => void
    themeId?: number | null
    colors?: never
    selectedColor?: never
    onSelectColor?: never
}

type LemonColorPickerProps = LemonColorPickerColorProps | LemonColorPickerTokenProps

type LemonColorPickerOverlayProps = Omit<LemonColorPickerProps, 'hideDropdown'>

export const LemonColorPickerOverlay = ({
    themeId,
    colors,
    colorTokens,
    selectedColor,
    selectedColorToken,
    onSelectColor,
    onSelectColorToken,
    showCustomColor = false,
    preventPopoverClose = false,
}: LemonColorPickerOverlayProps): JSX.Element => {
    const [color, setColor] = useState<string | null>(selectedColor || null)
    const [lastValidColor, setLastValidColor] = useState<string | null>(selectedColor || null)

    return (
        <div
            className="w-52 flex flex-col p-2"
            // prevents native event bubbling, so that popovers don't close
            onMouseUp={(e) => {
                if (preventPopoverClose) {
                    e.nativeEvent.stopImmediatePropagation()
                }
            }}
            onTouchEnd={(e) => {
                if (preventPopoverClose) {
                    e.nativeEvent.stopImmediatePropagation()
                }
            }}
        >
            <LemonLabel className="mt-1 mb-0.5">Preset colors</LemonLabel>
            {colors ? (
                <LemonColorList colors={colors} selectedColor={selectedColor} onSelectColor={onSelectColor} />
            ) : colorTokens ? (
                <LemonColorList
                    themeId={themeId}
                    colorTokens={colorTokens}
                    selectedColorToken={selectedColorToken}
                    onSelectColorToken={onSelectColorToken}
                />
            ) : null}
            {showCustomColor && (
                <div>
                    <LemonLabel className="mt-2 mb-0.5">Custom color</LemonLabel>
                    <div className="flex items-center gap-2">
                        <LemonColorGlyph color={lastValidColor} className="ml-1.5" />
                        <LemonInput
                            className="mt-1 font-mono"
                            size="small"
                            value={color || ''}
                            onChange={(color) => {
                                setColor(color)
                                if (color != null && color != selectedColor && /^#[0-9A-Fa-f]{6}$/.test(color)) {
                                    setLastValidColor(color)
                                    onSelectColor?.(color)
                                }
                            }}
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
                    {...(props.selectedColor !== undefined
                        ? { color: props.selectedColor }
                        : { colorToken: props.selectedColorToken, themeId: props.themeId })}
                    onClick={() => setIsOpen(!isOpen)}
                    sideIcon={hideDropdown ? null : undefined}
                />
            </div>
        </Popover>
    )
}
