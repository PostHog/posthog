import clsx from 'clsx'
import { forwardRef } from 'react'

import { LemonTag, LemonTagProps, LemonTagType } from '@posthog/lemon-ui'

// LemonTag's text colours for these types fall below 4.5:1 contrast on the trace view's surfaces in one theme or both.
// The `!` is required because LemonTag.scss sits outside Tailwind's cascade layers, so it beats any plain utility.
const READABLE_TEXT: Partial<Record<LemonTagType, string>> = {
    danger: '!text-danger-dark dark:!text-error',
    success: '!text-success-dark dark:!text-success-light',
    caution: '!text-primary dark:!text-danger-lighter',
}

export const ChipTag = forwardRef<HTMLDivElement, LemonTagProps>(function ChipTag(
    { type = 'default', className, ...rest },
    ref
): JSX.Element {
    return <LemonTag ref={ref} type={type} className={clsx(READABLE_TEXT[type], className)} {...rest} />
})
