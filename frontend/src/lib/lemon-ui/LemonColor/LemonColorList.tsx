import { DataColorToken } from 'lib/colors'

import { LemonColorButton } from './LemonColorButton'

type LemonColorListColorProps = {
    colors: string[]
    selectedColor?: string | null
    onSelectColor?: (color: string) => void
    onClearColor?: () => void
    colorTokens?: never
    selectedColorToken?: never
    onSelectColorToken?: never
    onClearColorToken?: never
    themeId?: never
}

type LemonColorListTokenProps = {
    colorTokens: DataColorToken[]
    selectedColorToken?: DataColorToken | null
    onSelectColorToken?: (colorToken: DataColorToken) => void
    onClearColorToken?: () => void
    themeId?: number | null
    colors?: never
    selectedColor?: never
    onSelectColor?: never
    onClearColor?: never
}

export type LemonColorListProps = LemonColorListColorProps | LemonColorListTokenProps

export function LemonColorList({
    colors,
    colorTokens,
    selectedColor,
    selectedColorToken,
    onSelectColor,
    onSelectColorToken,
    onClearColor,
    onClearColorToken,
    themeId,
}: LemonColorListProps): JSX.Element | null {
    if (colorTokens?.length) {
        return (
            <div className="flex flex-wrap gap-1">
                {onClearColorToken && (
                    <LemonColorButton
                        color={null}
                        type={selectedColorToken === null ? 'secondary' : 'tertiary'}
                        tooltip="No color"
                        onClick={(e) => {
                            e.preventDefault()
                            e.stopPropagation()

                            onClearColorToken()
                        }}
                    />
                )}
                {colorTokens.map((colorToken) => (
                    <LemonColorButton
                        key={colorToken}
                        colorToken={colorToken}
                        type={selectedColorToken === colorToken ? 'secondary' : 'tertiary'}
                        onClick={(e) => {
                            e.preventDefault()
                            e.stopPropagation()

                            onSelectColorToken?.(colorToken)
                        }}
                        themeId={themeId}
                    />
                ))}
            </div>
        )
    }

    if (colors?.length) {
        return (
            <div className="flex flex-wrap gap-1">
                {onClearColor && (
                    <LemonColorButton
                        color={null}
                        type={selectedColor === null ? 'secondary' : 'tertiary'}
                        tooltip="No color"
                        onClick={(e) => {
                            e.preventDefault()
                            e.stopPropagation()

                            onClearColor()
                        }}
                    />
                )}
                {colors.map((color) => (
                    <LemonColorButton
                        key={color}
                        color={color}
                        type={selectedColor === color ? 'secondary' : 'tertiary'}
                        onClick={(e) => {
                            e.preventDefault()
                            e.stopPropagation()

                            onSelectColor?.(color)
                        }}
                    />
                ))}
            </div>
        )
    }

    return null
}
