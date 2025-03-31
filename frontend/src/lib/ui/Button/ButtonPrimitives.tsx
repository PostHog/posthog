import './Button.css'

import { cva, type VariantProps } from 'cva'
import { cn } from 'lib/utils/css-classes'
import React, { createContext, forwardRef, ReactNode, useContext } from 'react'

/* -------------------------------------------------------------------------- */
/*                           Props & Contexts & Hooks                         */
/* -------------------------------------------------------------------------- */

type ButtonVariant = 'default' | 'default-group' | 'outline'

const BUTTON_HEIGHT_SM = 'h-[var(--button-height-sm)]'
const BUTTON_ICON_WIDTH_SM = 'w-[var(--button-height-sm)]'
const BUTTON_HEIGHT_BASE = 'h-[var(--button-height-base)]'
const BUTTON_ICON_WIDTH_BASE = 'w-[var(--button-height-base)]'
const BUTTON_HEIGHT_LG = 'h-[var(--button-height-lg)]'
const BUTTON_ICON_WIDTH_LG = 'w-[var(--button-height-lg)]'

const BUTTON_VARIANT: Record<ButtonVariant, string> = {
    'default-group': `
            border border-transparent
            text-primary 
            max-w-full
            [&>.button-primitive]:rounded-none
            [&>.button-primitive]:first:rounded-l-md
            [&>.button-primitive]:last:rounded-r-md
            [&>.button-primitive:not(:first-child)]:border-l-0
        `,
    default: `
            border border-transparent
            text-primary 
            max-w-full
            not-disabled:hover:bg-fill-button-tertiary-hover 
            data-[focused=true]:bg-fill-button-tertiary-hover 
            data-[active=true]:bg-fill-button-tertiary-active 
            data-[current=true]:bg-fill-button-tertiary-active 
            data-[state=open]:bg-fill-button-tertiary-active 
            data-[state=checked]:bg-fill-button-tertiary-active
            data-highlighted:bg-fill-button-tertiary-active
        `,
    outline: `
        border border-secondary
        not-disabled:hover:border-tertiary
        hover:bg-fill-button-tertiary-active
    `,
}

export type ButtonSize = 'sm' | 'base' | 'lg' | 'fit'

interface ButtonGroupContextValue {
    sizeContext: ButtonSize
    variantContext: ButtonVariant
}

const ButtonContext = createContext<ButtonGroupContextValue | null>(null)

function useButtonGroupContext(): ButtonGroupContextValue | null {
    const context = useContext(ButtonContext)
    return context
}

type ButtonGroupProps = {
    children: ReactNode
    className?: string
} & VariantProps<typeof buttonVariants>

type ButtonBaseProps = {
    iconOnly?: boolean
    showDivider?: boolean
    external?: boolean
    disabled?: boolean
    active?: boolean
    buttonWrapper?: (button: JSX.Element) => JSX.Element
} & VariantProps<typeof buttonVariants>

/* -------------------------------------------------------------------------- */
/*                              Button Group Variants                         */
/* -------------------------------------------------------------------------- */

/* -------------------------------------------------------------------------- */
/*                              Button Group Component                        */
/* -------------------------------------------------------------------------- */

export const ButtonGroupPrimitive = forwardRef<HTMLDivElement, ButtonGroupProps>((props, ref) => {
    const { className, variant = 'default', size = 'base', fullWidth = false, children, ...rest } = props
    const Comp = 'div'

    const setContext: ButtonGroupContextValue = {
        variantContext: variant,
        sizeContext: size,
    }

    let buttonHeight = ''
    switch (size) {
        case 'sm':
            buttonHeight = BUTTON_HEIGHT_SM
            break
        case 'base':
            buttonHeight = BUTTON_HEIGHT_BASE
            break
        case 'lg':
            buttonHeight = BUTTON_HEIGHT_LG
            break
        case 'fit':
            buttonHeight = ''
            break
    }

    return (
        <ButtonContext.Provider value={setContext}>
            <Comp
                className={cn(
                    buttonVariants({
                        size: 'fit',
                        variant: 'default-group',
                        fullWidth,
                        isGroup: true,
                        className,
                    }),
                    buttonHeight
                )}
                ref={ref}
                {...rest}
            >
                {children}
            </Comp>
        </ButtonContext.Provider>
    )
})

ButtonGroupPrimitive.displayName = 'ButtonGroupPrimitive'

/* -------------------------------------------------------------------------- */
/*                              Button Base Component                         */
/* -------------------------------------------------------------------------- */

interface ButtonAsButtonProps extends ButtonBaseProps, React.ButtonHTMLAttributes<HTMLButtonElement> {
    href?: never
}

interface ButtonAsAnchorProps extends ButtonBaseProps, Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, 'href'> {
    href: string
}

type ButtonProps = ButtonAsButtonProps | ButtonAsAnchorProps

const buttonVariants = cva({
    base: `
        button-primitive
        group/button-primitive
        inline-flex
        w-fit
        items-center
        rounded-md
        text-sm
        font-normal
        transition-colors
        aria-disabled:cursor-not-allowed
        aria-disabled:pointer-events-none
        aria-disabled:opacity-50
        text-current
        [&_svg]:shrink-0
    `,
    variants: {
        variant: {
            default: BUTTON_VARIANT.default,
            outline: BUTTON_VARIANT.outline,
            'default-group': BUTTON_VARIANT['default-group'],
        },
        size: {
            sm: `${BUTTON_HEIGHT_SM} px-[var(--button-padding-x-sm)] [&_svg]:size-3`,
            base: `${BUTTON_HEIGHT_BASE} px-[var(--button-padding-x-base)] [&_svg]:size-4`,
            lg: `${BUTTON_HEIGHT_LG} px-[var(--button-padding-x-lg)] [&_svg]:size-5`,
            fit: 'px-0',
        },
        iconOnly: {
            true: 'p-0',
            false: '',
        },
        fullWidth: {
            true: 'w-full',
            false: '',
        },
        isGroup: {
            true: '',
            false: 'gap-1.5',
        },
        menuItem: {
            true: 'w-full justify-start', // @TODO this isn't working
            false: '',
        },
        truncate: {
            true: 'truncate',
            false: '',
        },
        disabled: {
            true: 'disabled:pointer-events-none disabled:opacity-50',
            false: '',
        },
    },
    defaultVariants: {
        variant: 'default',
        size: 'base',
        fullWidth: false,
        isGroup: false,
        menuItem: false,
    },
    compoundVariants: [
        {
            iconOnly: true,
            size: 'sm',
            className: BUTTON_ICON_WIDTH_SM,
        },
        {
            iconOnly: true,
            size: 'base',
            className: BUTTON_ICON_WIDTH_BASE,
        },
        {
            iconOnly: true,
            size: 'lg',
            className: BUTTON_ICON_WIDTH_LG,
        },
    ],
})

export const ButtonPrimitive = forwardRef<HTMLButtonElement | HTMLAnchorElement, ButtonProps>((props, ref) => {
    const {
        className,
        variant,
        size,
        fullWidth,
        href,
        external,
        children,
        iconOnly,
        menuItem,
        disabled,
        active,
        buttonWrapper,
        ...rest
    } = props
    // If inside a ButtonGroup, use the context values, otherwise use props
    const context = useButtonGroupContext()
    const effectiveSize = context?.sizeContext || size
    const effectiveVariant = context?.variantContext || variant
    // Determine the component type
    const Comp = href ? 'a' : 'button'
    // Determine the external props
    const externalProps = external && href ? { target: '_blank' } : {}
    // Determine the element props
    const elementProps = href ? { href, ...rest } : rest

    const buttonComponent = React.createElement(
        Comp,
        {
            className: cn(
                buttonVariants({
                    variant: effectiveVariant,
                    size: effectiveSize,
                    fullWidth,
                    iconOnly,
                    menuItem,
                    disabled,
                    className,
                })
            ),
            ref,
            ...externalProps,
            ...elementProps,
            'aria-disabled': disabled,
            'data-active': active,
        },
        children
    )

    if (buttonWrapper) {
        return buttonWrapper(buttonComponent)
    }

    return buttonComponent
})

ButtonPrimitive.displayName = 'ButtonPrimitive'
