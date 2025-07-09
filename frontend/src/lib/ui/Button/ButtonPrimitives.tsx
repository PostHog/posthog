import './ButtonPrimitives.scss'

import { cva, type VariantProps } from 'cva'
import { Tooltip, TooltipProps } from 'lib/lemon-ui/Tooltip/Tooltip'
import { cn } from 'lib/utils/css-classes'
import React, { createContext, forwardRef, ReactNode, useContext } from 'react'

/* -------------------------------------------------------------------------- */
/*                           Props & Contexts & Hooks                         */
/* -------------------------------------------------------------------------- */

type ButtonVariant = 'default' | 'outline'

export type ButtonSize = 'sm' | 'base' | 'lg' | 'fit' | 'base-tall'

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
} & VariantProps<typeof buttonPrimitiveVariants>

type ButtonBaseProps = {
    iconOnly?: boolean
    showDivider?: boolean
    disabled?: boolean
    active?: boolean
    tooltip?: TooltipProps['title']
    tooltipDocLink?: TooltipProps['docLink']
    tooltipPlacement?: TooltipProps['placement']
    buttonWrapper?: (button: JSX.Element) => JSX.Element
} & VariantProps<typeof buttonPrimitiveVariants>

/* -------------------------------------------------------------------------- */
/*                              Button Group Variants                         */
/* -------------------------------------------------------------------------- */

/* -------------------------------------------------------------------------- */
/*                              Button Group Component                        */
/* -------------------------------------------------------------------------- */

export const ButtonGroupPrimitive = forwardRef<HTMLDivElement, ButtonGroupProps>((props, ref) => {
    const {
        className,
        groupVariant = 'default',
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

    let buttonHeight = 'button-primitive--height-base'
    switch (size) {
        case 'sm':
            buttonHeight = 'button-primitive--height-sm'
            break
        case 'base-tall':
            buttonHeight = 'button-primitive--height-base-tall'
            break
        case 'lg':
            buttonHeight = 'button-primitive--height-lg'
            break
        case 'fit':
            buttonHeight = ''
            break
    }

    return (
        <ButtonContext.Provider value={setContext}>
            <Comp
                className={cn(
                    'button-primitive-group',
                    buttonPrimitiveVariants({
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

export interface ButtonPrimitiveProps extends ButtonBaseProps, React.ButtonHTMLAttributes<HTMLButtonElement> {}

export const buttonPrimitiveVariants = cva({
    base: 'button-primitive group/button-primitive',
    variants: {
        variant: {
            // Bordereless variant (aka posthog tertiary button)
            default: 'button-primitive--variant-default',
            // Outline variant (aka posthog secondary button)
            outline: 'button-primitive--variant-outline',
        },
        size: {
            sm: `button-primitive--size-sm button-primitive--height-sm text-sm`,
            base: `button-primitive--size-base button-primitive--height-base text-sm`,
            'base-tall': `button-primitive--size-base-tall button-primitive--height-base-tall text-sm`,
            lg: `button-primitive--size-lg button-primitive--height-lg text-base`,
            fit: 'px-0',
        },
        iconOnly: {
            true: 'icon-only p-0 justify-center items-center shrink-0',
            false: '',
        },
        fullWidth: {
            true: 'button-primitive--full-width',
            false: '',
        },
        isGroup: {
            true: '',
            false: 'gap-1.5',
        },
        active: {
            true: 'button-primitive--active',
            false: '',
        },
        menuItem: {
            true: 'rounded-sm button-primitive--full-width justify-start shrink-0',
            false: '',
        },
        truncate: {
            true: 'truncate',
            false: '',
        },
        disabled: {
            true: 'disabled:opacity-50',
            false: '',
        },
        hasSideActionRight: {
            true: 'rounded-md',
            false: '',
        },
        isSideActionRight: {
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
            hasSideActionRight: true,
            size: 'sm',
            className: `
                pr-[calc(var(--button-height-sm)+var(--button-padding-x-sm))]
            `,
        },
        {
            hasSideActionRight: true,
            size: 'base',
            className: `
                pr-[calc(var(--button-height-base)+var(--button-padding-x-base))]
            `,
        },
        {
            hasSideActionRight: true,
            size: 'lg',
            className: `
                pr-[calc(var(--button-height-lg)+var(--button-padding-x-lg))]
            `,
        },
    ],
})

export const ButtonPrimitive = forwardRef<HTMLButtonElement, ButtonPrimitiveProps>((props, ref) => {
    const {
        className,
        variant,
        size,
        fullWidth,
        children,
        iconOnly,
        menuItem,
        disabled,
        active,
        buttonWrapper,
        hasSideActionRight,
        isSideActionRight,
        tooltip,
        tooltipPlacement,
        tooltipDocLink,
        ...rest
    } = props
    // If inside a ButtonGroup, use the context values, otherwise use props
    const context = useButtonGroupContext()
    const effectiveSize = context?.sizeContext || size
    const effectiveVariant = context?.variantContext || variant

    let buttonComponent: JSX.Element = React.createElement(
        'button',
        {
            className: cn(
                buttonPrimitiveVariants({
                    variant: effectiveVariant,
                    size: effectiveSize,
                    fullWidth,
                    iconOnly,
                    menuItem,
                    disabled,
                    hasSideActionRight,
                    isSideActionRight,
                    className,
                })
            ),
            ref,
            disabled,
            ...rest,
            'aria-disabled': disabled,
            'data-active': active,
        },
        children
    )

    if (tooltip || tooltipDocLink) {
        buttonComponent = (
            <Tooltip title={tooltip} placement={tooltipPlacement} docLink={tooltipDocLink}>
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
