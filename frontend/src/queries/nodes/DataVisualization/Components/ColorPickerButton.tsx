import { LemonButton, Popover } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'
import { hexToRGBA, lightenDarkenColor, RGBToHex, RGBToRGBA } from 'lib/utils'
import { useState } from 'react'
import { ColorResult, TwitterPicker } from 'react-color'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

const DEFAULT_PICKER_COLORS = [
    '#FFADAD', // Current default
    '#E8A598',
    '#FFD6A5',
    '#FFCFD2',
    '#FDFFB6',
    '#C1FBA4',
    '#9BF6FF',
    '#A0C4FF',
    '#BDB2FF',
    '#FFC6FF',
]

export const ColorPickerButton = ({
    color,
    onColorSelect: propOnColorSelect,
    colorChoices = DEFAULT_PICKER_COLORS,
}: {
    color: string
    onColorSelect?: (color: string) => void
    colorChoices?: string[]
}): JSX.Element => {
    const [pickerOpen, setPickerOpen] = useState(false)
    const { isDarkModeOn } = useValues(themeLogic)

    const onColorSelect = (colorResult: ColorResult): void => {
        if (propOnColorSelect) {
            propOnColorSelect(colorResult.hex)
        }

        if (colorChoices.includes(colorResult.hex)) {
            setPickerOpen(false)
        }
    }

    const colors = isDarkModeOn ? colorChoices.map((n) => RGBToHex(lightenDarkenColor(n, -30))) : colorChoices

    return (
        <Popover
            visible={pickerOpen}
            overlay={<TwitterPicker color={color} colors={colors} onChangeComplete={onColorSelect} />}
            onClickOutside={() => setPickerOpen(false)}
            padded={false}
        >
            <LemonButton
                type="secondary"
                onClick={() => setPickerOpen(!pickerOpen)}
                sideIcon={<></>}
                className="ConditionalFormattingTab__ColorPicker"
            >
                <SeriesGlyph
                    style={{
                        borderColor: color,
                        color: color,
                        backgroundColor: isDarkModeOn
                            ? RGBToRGBA(lightenDarkenColor(color, -20), 0.3)
                            : hexToRGBA(color, 0.5),
                    }}
                >
                    <></>
                </SeriesGlyph>
            </LemonButton>
        </Popover>
    )
}
