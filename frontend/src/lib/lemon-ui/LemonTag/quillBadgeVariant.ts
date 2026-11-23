import type { ComponentProps } from 'react'

import type { Badge } from '@posthog/quill'

import type { LemonTagType } from './LemonTag'

export type QuillBadgeVariant = NonNullable<ComponentProps<typeof Badge>['variant']>

const VARIANT_BY_TYPE: Record<LemonTagType, QuillBadgeVariant> = {
    primary: 'info',
    option: 'default',
    highlight: 'info',
    info: 'info',
    warning: 'warning',
    danger: 'destructive',
    success: 'success',
    default: 'default',
    muted: 'default',
    completion: 'completed',
    caution: 'warning',
    none: 'default',
}

export function quillBadgeVariant(type: LemonTagType | undefined): QuillBadgeVariant {
    return type ? VARIANT_BY_TYPE[type] : 'default'
}
