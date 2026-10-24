import type { ButtonProps } from '@posthog/quill'

import type { LemonButtonPropsBase } from './LemonButton'

type QuillButtonVariant = NonNullable<ButtonProps['variant']>
type QuillButtonSize = NonNullable<ButtonProps['size']>
type QuillTextSize = 'xs' | 'sm' | 'default' | 'lg'

const TEXT_SIZES: Record<NonNullable<LemonButtonPropsBase['size']>, QuillTextSize> = {
    xxsmall: 'xs',
    xsmall: 'sm',
    small: 'default',
    medium: 'default',
    large: 'lg',
}

const ICON_SIZES: Record<QuillTextSize, QuillButtonSize> = {
    xs: 'icon-xs',
    sm: 'icon-sm',
    default: 'icon',
    lg: 'icon-lg',
}

export function quillButtonVariant(
    type: LemonButtonPropsBase['type'],
    status: LemonButtonPropsBase['status'],
    row: boolean
): QuillButtonVariant {
    const danger = status === 'danger'
    if (row) {
        // Matches quill's destructive DropdownMenuItem
        return danger ? 'destructive' : 'default'
    }
    if (type === 'primary') {
        return danger ? 'destructive' : 'primary'
    }
    if (type === 'secondary') {
        return danger ? 'destructive-outline' : 'outline'
    }
    return 'default'
}

export function quillButtonSize(size: LemonButtonPropsBase['size'], iconOnly: boolean, row: boolean): QuillButtonSize {
    if (row && !iconOnly) {
        return 'row'
    }
    const textSize = TEXT_SIZES[size ?? 'medium']
    return iconOnly ? ICON_SIZES[textSize] : textSize
}
