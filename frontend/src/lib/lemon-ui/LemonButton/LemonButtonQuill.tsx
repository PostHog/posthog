import clsx from 'clsx'
import React from 'react'

import { Button, buttonVariants } from '@posthog/quill'

import { LinkPrimitive } from '../Link'
import type { LemonButtonPropsBase } from './LemonButton'
import { quillButtonSize, quillButtonVariant } from './lemonButtonQuillProps'

type LemonButtonQuillOwnProps = Pick<
    LemonButtonPropsBase,
    | 'type'
    | 'status'
    | 'size'
    | 'loading'
    | 'fullWidth'
    | 'center'
    | 'className'
    | 'active'
    | 'disabled'
    | 'htmlType'
    | 'targetBlank'
    | 'disableClientSideRouting'
> & {
    /** Navigation target. Leave empty when the button is disabled, so it renders a button and not a link. */
    linkTo?: string
    iconOnly: boolean
    row?: boolean
    onClick: (event: React.MouseEvent<HTMLElement>) => void
    children: React.ReactNode
}

/** DOM, ARIA and data attributes pass through, including the handlers that a wrapping Tooltip or LemonDropdown adds. */
type LemonButtonQuillElementProps = Omit<React.ButtonHTMLAttributes<HTMLElement>, keyof LemonButtonQuillOwnProps> &
    Pick<LemonButtonPropsBase, 'data-attr' | 'data-attr-id'>

export type LemonButtonQuillProps = LemonButtonQuillOwnProps & LemonButtonQuillElementProps

/** The quill rendering of LemonButton, used when the today-rail-nav redesign is on. */
export const LemonButtonQuill = React.forwardRef<HTMLButtonElement, LemonButtonQuillProps>(function LemonButtonQuill(
    {
        type,
        status,
        size,
        loading,
        fullWidth,
        center,
        className,
        active,
        disabled,
        htmlType,
        targetBlank,
        disableClientSideRouting,
        linkTo,
        iconOnly,
        row = false,
        onClick,
        children,
        ...elementProps
    },
    ref
): JSX.Element {
    const variant = quillButtonVariant(type, status, row)
    const quillSize = quillButtonSize(size, iconOnly, row)
    const left = row || (!!fullWidth && !center)
    const extraClassName = clsx(
        fullWidth && 'w-full',
        // quill buttons center text, so multi-line content would center each line under the left-aligned icon
        left && 'text-start',
        // Rows can hold a title and a description line, so they grow past the fixed row height
        row && 'h-auto min-h-7',
        // The quill bridge scopes `text-destructive-foreground` to descendants of `[data-quill]`, not to the element itself
        !row && type === 'tertiary' && status === 'danger' && 'text-[var(--destructive-foreground)]',
        className
    )
    const sharedProps = {
        'data-popup-open': active ? '' : undefined,
        onClick,
        // ARIA disabled, not native, so the disabled reason tooltip still opens on hover and click
        'aria-disabled': !!disabled,
        ...elementProps,
    }

    if (linkTo) {
        // quill's Button gives a non-native element role="button". Navigation must keep the link role.
        return (
            <LinkPrimitive
                ref={ref}
                to={linkTo}
                target={targetBlank ? '_blank' : undefined}
                disableClientSideRouting={disableClientSideRouting}
                data-quill
                data-slot="button"
                data-size={quillSize}
                className={clsx(buttonVariants({ variant, size: quillSize, left }), extraClassName)}
                {...sharedProps}
            >
                {children}
            </LinkPrimitive>
        )
    }

    return (
        <Button
            ref={ref}
            variant={variant}
            size={quillSize}
            left={left}
            loading={loading}
            className={extraClassName}
            type={htmlType}
            {...sharedProps}
        >
            {children}
        </Button>
    )
})
