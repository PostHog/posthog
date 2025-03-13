import { DataColorToken } from 'lib/colors'

import { LemonColorButton } from './LemonColorButton'

type LemonColorListProps = {
    colors?: string[]
    colorTokens?: DataColorToken[]
    selectedColor?: string | null
    selectedColorToken?: DataColorToken | null
    onClick: {
        (color: string): void
        (colorToken: DataColorToken): void
    }
}

export function LemonColorList({
    colors,
    colorTokens,
    selectedColor,
    selectedColorToken,
    onClick,
}: LemonColorListProps): JSX.Element | null {
    if (colorTokens?.length) {
        return (
            <div className="flex flex-wrap gap-1">
                {colorTokens.map((colorToken) => (
                    <LemonColorButton
                        key={colorToken}
                        colorToken={colorToken}
                        type={selectedColorToken === colorToken ? 'secondary' : 'tertiary'}
                        onClick={(e) => {
                            e.preventDefault()
                            e.stopPropagation()

                            onClick(colorToken)
                        }}
                    />
                ))}
            </div>
        )
    }

    if (colors?.length) {
        return (
            <div className="flex flex-wrap gap-1">
                {colors.map((color) => (
                    <LemonColorButton
                        key={color}
                        color={color}
                        type={selectedColor === color ? 'secondary' : 'tertiary'}
                        onClick={(e) => {
                            e.preventDefault()
                            e.stopPropagation()

                            onClick(color)
                        }}
                    />
                ))}
            </div>
        )
    }

    return null
}
