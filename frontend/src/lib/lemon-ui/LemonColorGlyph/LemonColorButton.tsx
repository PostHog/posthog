import './LemonColorButton.scss'

import { cn } from 'lib/utils/css-classes'

import { LemonButton, LemonButtonProps } from '../LemonButton'
import { LemonColorGlyph } from './LemonColorGlyph'

type LemonColorButtonProps = LemonButtonProps & {
    color: string
}

export function LemonColorButton({
    color,
    type = 'secondary',
    className,
    ...rest
}: LemonColorButtonProps): JSX.Element {
    return (
        <LemonButton type={type} className={cn('LemonColorButton', className)} {...rest}>
            <LemonColorGlyph color={color} />
        </LemonButton>
    )
}
