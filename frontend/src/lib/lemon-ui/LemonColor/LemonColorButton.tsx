import './LemonColorButton.scss'

import { useValues } from 'kea'

import { DataColorToken } from 'lib/colors'
import { cn } from 'lib/utils/css-classes'
import { dataThemeLogic } from 'scenes/dataThemeLogic'

import { LemonButton, LemonButtonWithoutSideActionProps } from '../LemonButton'
import { LemonColorGlyph } from './LemonColorGlyph'
import { colorDescription } from './utils'

type LemonColorButtonBaseProps = LemonButtonWithoutSideActionProps & {
    hideColorDescription?: boolean
}

type LemonColorButtonColorProps = LemonColorButtonBaseProps & {
    color?: string | null
    colorToken?: never
    themeId?: never
}

type LemonColorButtonTokenProps = LemonColorButtonBaseProps & {
    colorToken?: DataColorToken | null
    themeId?: number | null
    color?: never
}

export type LemonColorButtonProps = LemonColorButtonColorProps | LemonColorButtonTokenProps

export function LemonColorButton({
    type = 'secondary',
    className,
    color,
    colorToken,
    themeId,
    tooltip,
    hideColorDescription = false,
    size,
    ...rest
}: LemonColorButtonProps): JSX.Element {
    const { getColorFromToken } = useValues(dataThemeLogic)

    // we need to derive the color here as well for the tooltip
    const effectiveColor = colorToken ? getColorFromToken(themeId, colorToken) : color
    const derivedTooltip = hideColorDescription || !effectiveColor ? undefined : colorDescription(effectiveColor)
    const effectiveTooltip = tooltip ?? derivedTooltip

    return (
        <LemonButton
            type={type}
            size={size}
            className={cn('LemonColorButton', className)}
            tooltip={effectiveTooltip}
            {...rest}
        >
            {colorToken ? (
                <LemonColorGlyph colorToken={colorToken} size={size} themeId={themeId} />
            ) : (
                <LemonColorGlyph color={color} size={size} />
            )}
        </LemonButton>
    )
}
