import './ButtonPrimitives.css'

import { cva, type VariantProps } from 'cva'
import { Tooltip, TooltipProps } from 'lib/lemon-ui/Tooltip/Tooltip'
import { cn } from 'lib/utils/css-classes'
import React, { createContext, forwardRef, ReactNode, useContext } from 'react'

/* -------------------------------------------------------------------------- */
/*                           Props & Contexts & Hooks                         */
/* -------------------------------------------------------------------------- */

type ButtonVariant = 'default' | 'outline' | 'default-group' | 'side-action-group'

const BUTTON_HEIGHT_SM = 'h-[var(--button-height-sm)]'
const BUTTON_ICON_WIDTH_SM = 'w-[var(--button-height-sm)]'
const BUTTON_HEIGHT_BASE = 'h-[var(--button-height-base)]'
const BUTTON_ICON_WIDTH_BASE = 'w-[var(--button-height-base)]'
const BUTTON_HEIGHT_LG = 'h-[var(--button-height-lg)]'
const BUTTON_ICON_WIDTH_LG = 'w-[var(--button-height-lg)]'

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
    groupVariant?: ButtonVariant
} & VariantProps<typeof buttonVariants>

type ButtonBaseProps = {
    iconOnly?: boolean
    showDivider?: boolean
    external?: boolean
    disabled?: boolean
    active?: boolean
    tooltip?: TooltipProps['title']
    tooltipPlacement?: TooltipProps['placement']
    buttonWrapper?: (button: JSX.Element) => JSX.Element
} & VariantProps<typeof buttonVariants>

/* -------------------------------------------------------------------------- */
/*                              Button Group Variants                         */
/* -------------------------------------------------------------------------- */

/* -------------------------------------------------------------------------- */
/*                              Button Group Component                        */
/* -------------------------------------------------------------------------- */

export const ButtonGroupPrimitive = forwardRef<HTMLDivElement, ButtonGroupProps>((props, ref) => {
    const {
        className,
        groupVariant = 'default-group',
        variant = 'default',
        size = 'base',
        fullWidth = false,
        children,
        ...rest
    } = props
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
                        variant: groupVariant,
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
        relative
        items-center
        rounded-md
        font-normal
        aria-disabled:cursor-not-allowed
        aria-disabled:pointer-events-none
        aria-disabled:opacity-50
        text-current
        [&_svg]:shrink-0
    `,
    variants: {
        variant: {
            // Bordereless variant (aka posthog tertiary button)
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
            // Outline variant (aka posthog secondary button)
            outline: `
                border border-secondary
                not-disabled:hover:border-tertiary
                hover:bg-fill-button-tertiary-active
            `,
            // Buttons next to each other
            'default-group': `
                border border-transparent
                text-primary 
                max-w-full
                [&_.button-primitive]:rounded-none
                [&_.button-primitive]:first:rounded-l-md
                [&_.button-primitive]:last:rounded-r-md
                [&_.button-primitive:not(:first-child)]:border-l-0
            `,
            'side-action-group': `
                border border-transparent
                text-primary 
                max-w-full
            `,
        },
        size: {
            sm: `button-primitive-size-sm ${BUTTON_HEIGHT_SM} text-xs pl-[var(--button-padding-x-sm)] pr-[var(--button-padding-x-sm)]`,
            base: `button-primitive-size-base ${BUTTON_HEIGHT_BASE} text-sm pl-[var(--button-padding-x-base)] pr-[var(--button-padding-x-base)]`,
            lg: `button-primitive-size-lg ${BUTTON_HEIGHT_LG} text-base pl-[var(--button-padding-x-lg)] pr-[var(--button-padding-x-lg)]`,
            fit: 'px-0',
        },
        iconOnly: {
            true: 'p-0 justify-center items-center shrink-0',
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
        sideActionLeft: {
            true: 'rounded-md',
            false: '',
        },
        sideActionRight: {
            true: 'absolute right-0 -top-px -bottom-px rounded-l-none',
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
        {
            sideActionLeft: true,
            size: 'sm',
            className: `
                pr-[calc(var(--button-height-sm)+var(--button-padding-x-sm))]
            `,
        },
        {
            sideActionLeft: true,
            size: 'base',
            className: `
                pr-[calc(var(--button-height-base)+var(--button-padding-x-base))]
            `,
        },
        {
            sideActionLeft: true,
            size: 'lg',
            className: `
                pr-[calc(var(--button-height-lg)+var(--button-padding-x-lg))]
            `,
        },
        // {
        //     sideActionRight: true,
        //     className: `
        //         rounded-l-none
        //     `,
        // },
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
        sideActionLeft,
        sideActionRight,
        tooltip,
        tooltipPlacement,
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

    let buttonComponent: JSX.Element = React.createElement(
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
                    sideActionLeft,
                    sideActionRight,
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

    if (tooltip) {
        buttonComponent = (
            <Tooltip title={tooltip} placement={tooltipPlacement}>
                {buttonComponent}
            </Tooltip>
        )
    }

    if (buttonWrapper) {
        buttonComponent = buttonWrapper(buttonComponent)
    }

    return buttonComponent
})

ButtonPrimitive.displayName = 'ButtonPrimitive'
