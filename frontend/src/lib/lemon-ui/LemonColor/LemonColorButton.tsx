import './LemonColorButton.scss'

import { useValues } from 'kea'
import { DataColorToken } from 'lib/colors'
import { cn } from 'lib/utils/css-classes'
import { dataThemeLogic } from 'scenes/dataThemeLogic'

import { LemonButton, LemonButtonWithoutSideActionProps } from '../LemonButton'
import { LemonColorGlyph, LemonColorGlyphProps } from './LemonColorGlyph'
import { colorDescription } from './utils'

type LemonColorButtonBaseProps = Pick<LemonColorGlyphProps, 'themeId'> &
    LemonButtonWithoutSideActionProps & { hideColorDescription?: boolean }

type LemonColorButtonColorProps = LemonColorButtonBaseProps & {
    color?: string | null
    colorToken?: never
}

type LemonColorButtonTokenProps = LemonColorButtonBaseProps & {
    colorToken?: DataColorToken | null
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
    const { getTheme } = useValues(dataThemeLogic)

    const theme = getTheme(themeId)

    const effectiveColor = colorToken ? (theme?.[colorToken] as string) : color
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
            <LemonColorGlyph color={effectiveColor} size={size} themeId={themeId} />
        </LemonButton>
    )
}
