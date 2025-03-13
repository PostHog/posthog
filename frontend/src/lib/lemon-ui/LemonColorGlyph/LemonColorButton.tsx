import './LemonColorButton.scss'

import { cn } from 'lib/utils/css-classes'

import { LemonButton, LemonButtonProps } from '../LemonButton'
import { LemonColorGlyph, LemonColorGlyphProps } from './LemonColorGlyph'

export type LemonColorButtonProps = Pick<LemonColorGlyphProps, 'themeId' | 'color' | 'colorToken'> & LemonButtonProps

export function LemonColorButton({
    type = 'secondary',
    className,
    color,
    colorToken,
    themeId,
    ...rest
}: LemonColorButtonProps): JSX.Element {
    return (
        <LemonButton type={type} className={cn('LemonColorButton', className)} {...rest}>
            <LemonColorGlyph color={color} colorToken={colorToken} themeId={themeId} />
        </LemonButton>
    )
}
