import './button.css'

import { Button as ButtonPrimitive } from '@base-ui/react/button'
import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import { cn } from './lib/utils'
import { Spinner } from './spinner'
import { hasTooltipContent, withTooltip } from './with-tooltip'

const buttonVariants = cva(
    'quill-button group/button inline-flex shrink-0 items-center justify-center whitespace-nowrap',
    {
        variants: {
            variant: {
                default: 'quill-button--variant-default',
                primary: 'quill-button--variant-primary',
                secondary: 'quill-button--variant-secondary',
                outline: 'quill-button--variant-outline',
                destructive: 'quill-button--variant-destructive',
                'destructive-outline': 'quill-button--variant-destructive-outline',
                link: 'quill-button--variant-link',
                'link-muted': 'quill-button--variant-link-muted',
            },
            size: {
                default: 'quill-button--size-default',
                xs: 'quill-button--size-xs',
                sm: 'quill-button--size-sm',
                inline: 'quill-button--size-inline',
                lg: 'quill-button--size-lg',
                icon: 'quill-button--size-icon',
                'icon-xs': 'quill-button--size-icon-xs',
                'icon-sm': 'quill-button--size-icon-sm',
                'icon-lg': 'quill-button--size-icon-lg',
                row: 'quill-button--size-row',
            },
            focusableWhenDisabled: {
                true: '',
                false: 'quill-button--not-focusable-when-disabled',
            },
            left: {
                true: 'justify-start',
                false: '',
            },
            inert: {
                true: 'quill-button--inert',
                false: '',
            },
            elevated: {
                true: 'quill-button--elevated',
                false: '',
            },
        },
        defaultVariants: {
            variant: 'default',
            size: 'default',
        },
    }
)

export type ButtonProps = ButtonPrimitive.Props &
    VariantProps<typeof buttonVariants> & {
        /** Hides the label under a centered spinner and disables the button. Width stays stable. */
        loading?: boolean
        /**
         * Chunky raised chrome (heavy edge + bottom ledge) for strong calls to action.
         * Use with `primary` or `outline`. At most two in a row; any further button is a flat `default`. See AGENTS.md.
         */
        elevated?: boolean
        /** Text shown on hover and focus. Icon-only buttons need one, matching their `aria-label`. */
        tooltip?: React.ReactNode
        /**
         * Disables the button and says why in its tooltip. The button stays hoverable and focusable,
         * so the reason is always reachable. Takes the place of `tooltip` while set. A rendered link
         * loses its destination while disabled, so a modifier click cannot open it either.
         */
        disabledReason?: React.ReactNode
    }

/** A `render` element that is not a `<button>` (a router link, an `<a>`) needs Base UI's non-native button handling. */
function rendersNonButton(render: ButtonPrimitive.Props['render']): boolean {
    return React.isValidElement(render) && render.type !== 'button'
}

/**
 * A disabled button keeps no destination. The browser handles a modifier click on a rendered link
 * before any click guard runs, so a kept `href` or `to` would still open in a new tab.
 */
function withoutDestination(render: ButtonPrimitive.Props['render']): ButtonPrimitive.Props['render'] {
    if (!React.isValidElement<{ to?: unknown; href?: unknown }>(render)) {
        return render
    }
    if (render.props.to === undefined && render.props.href === undefined) {
        return render
    }
    return React.cloneElement(render, { to: undefined, href: undefined })
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
    (
        {
            className,
            variant = 'default',
            size = 'default',
            focusableWhenDisabled = true,
            left = false,
            elevated = false,
            loading = false,
            disabled,
            tooltip,
            disabledReason,
            nativeButton,
            render,
            children,
            ...props
        },
        ref
    ) => {
        const hasDisabledReason = hasTooltipContent(disabledReason)
        const isDisabled = disabled || loading || hasDisabledReason
        const button = (
            <ButtonPrimitive
                ref={ref}
                data-quill
                data-slot="button"
                data-size={size}
                data-loading={loading || undefined}
                aria-busy={loading || undefined}
                disabled={isDisabled}
                nativeButton={nativeButton ?? !rendersNonButton(render)}
                render={isDisabled ? withoutDestination(render) : render}
                // While loading, stay focusable: Base UI then renders aria-disabled instead of
                // the native disabled attribute, keeping the button in the tab order so screen
                // readers can reach it and announce busy. Activation stays blocked. A disabled
                // reason needs the same, because its tooltip only opens on hover or focus.
                focusableWhenDisabled={loading || hasDisabledReason ? true : focusableWhenDisabled}
                className={cn(buttonVariants({ variant, size, className, focusableWhenDisabled, left, elevated }))}
                {...props}
            >
                {children}
                {loading && <Spinner className="quill-button__spinner" />}
            </ButtonPrimitive>
        )
        return withTooltip(button, hasDisabledReason ? disabledReason : tooltip, {
            target: 'self',
            delay: size?.startsWith('icon') ? 0 : undefined,
        })
    }
)
Button.displayName = 'Button'

export { Button, buttonVariants }
