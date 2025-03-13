import './LemonColorButton.scss'

import { useValues } from 'kea'
import { cn } from 'lib/utils/css-classes'
import { dataThemeLogic } from 'scenes/dataThemeLogic'

import { LemonButton, LemonButtonWithoutSideActionProps } from '../LemonButton'
import { LemonColorGlyph, LemonColorGlyphProps } from './LemonColorGlyph'
import { colorDescription } from './utils'

export type LemonColorButtonProps = Pick<LemonColorGlyphProps, 'themeId' | 'color' | 'colorToken'> &
    LemonButtonWithoutSideActionProps & { hideColorDescription?: boolean }

export function LemonColorButton({
    type = 'secondary',
    className,
    color,
    colorToken,
    themeId,
    tooltip,
    hideColorDescription = false,
    ...rest
}: LemonColorButtonProps): JSX.Element {
    const { getTheme } = useValues(dataThemeLogic)

    const theme = getTheme(themeId)

    const effectiveColor = colorToken ? (theme?.[colorToken] as string) : color
    const derivedTooltip = hideColorDescription || !effectiveColor ? undefined : colorDescription(effectiveColor)
    const effectiveTooltip = tooltip ?? derivedTooltip

    return (
        <LemonButton type={type} className={cn('LemonColorButton', className)} tooltip={effectiveTooltip} {...rest}>
            <LemonColorGlyph color={effectiveColor} themeId={themeId} />
        </LemonButton>
    )
}
