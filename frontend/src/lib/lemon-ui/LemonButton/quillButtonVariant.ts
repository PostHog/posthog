import type { LemonButtonProps } from './LemonButton'

const VARIANT_BY_TYPE = {
    primary: 'primary',
    secondary: 'outline',
    tertiary: 'default',
} as const

export function quillButtonVariant(type: LemonButtonProps['type']): 'primary' | 'outline' | 'default' {
    return type ? VARIANT_BY_TYPE[type] : 'default'
}
