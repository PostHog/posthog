import { Meta, StoryObj } from '@storybook/react'
import { DataColorToken, dataColorVars, getColorVar } from 'lib/colors'

import { LemonColorButton as LemonColorButtonComponent } from './LemonColorButton'
import { LemonColorGlyph as LemonColorGlyphComponent } from './LemonColorGlyph'
import { LemonColorList as LemonColorListComponent } from './LemonColorList'
type Story = StoryObj<typeof LemonColorGlyphComponent>
const meta: Meta<typeof LemonColorGlyphComponent> = {
    title: 'Lemon UI/Lemon Color',
    component: LemonColorGlyphComponent,
    tags: ['autodocs'],
}
export default meta

const colorTokens: DataColorToken[] = Array.from({ length: 15 }, (_, i) => `preset-${i + 1}` as DataColorToken)

export const LemonColorGlyph: Story = {
    render: () => (
        <div>
            <div className="flex gap-1 flex-wrap">
                <LemonColorGlyphComponent color="#ff0000" />
                <LemonColorGlyphComponent color="#00ff00" />
                <LemonColorGlyphComponent color="#0000ff" />
                {colorTokens.map((token) => (
                    <LemonColorGlyphComponent key={token} colorToken={token} />
                ))}
                <LemonColorGlyphComponent color={null} />
            </div>
            <div className="flex gap-1 flex-wrap">
                <LemonColorGlyphComponent color="#ff0000" size="small" />
                <LemonColorGlyphComponent color="#00ff00" size="small" />
                <LemonColorGlyphComponent color="#0000ff" size="small" />
                {colorTokens.map((token) => (
                    <LemonColorGlyphComponent key={token} colorToken={token} size="small" />
                ))}
                <LemonColorGlyphComponent color={null} size="small" />
            </div>
        </div>
    ),
}

export const LemonColorButton: Story = {
    render: () => (
        <div className="flex gap-1 flex-wrap">
            <LemonColorButtonComponent color={getColorVar(dataColorVars[0])} />
            <LemonColorButtonComponent type="tertiary" color={getColorVar(dataColorVars[0])} />
            <LemonColorButtonComponent color={getColorVar(dataColorVars[0])} size="small" />
            <LemonColorButtonComponent type="tertiary" color={getColorVar(dataColorVars[0])} size="small" />
        </div>
    ),
}

export const LemonColorList: Story = {
    render: () => (
        <>
            <div className="flex gap-1 flex-wrap">
                <LemonColorListComponent
                    colorTokens={colorTokens}
                    selectedColorToken={colorTokens[3]}
                    onClick={(colorToken) => {
                        alert(colorToken)
                    }}
                />
            </div>
            <div className="flex gap-1 flex-wrap">
                <LemonColorListComponent
                    colors={dataColorVars.map((colorVar) => getColorVar(colorVar))}
                    selectedColor={getColorVar(dataColorVars[3])}
                    onClick={(color) => {
                        alert(color)
                    }}
                />
            </div>
        </>
    ),
}
