import './ButtonPrimitives.scss'

import { type VariantProps, cva } from 'cva'
import React, { ReactNode, createContext, forwardRef, useContext } from 'react'

import { SceneShortcut, SceneShortcutProps } from 'lib/components/SceneShortcuts/SceneShortcut'
import { Tooltip, TooltipProps } from 'lib/lemon-ui/Tooltip/Tooltip'
import { cn } from 'lib/utils/css-classes'

/* -------------------------------------------------------------------------- */
/*                           Props & Contexts & Hooks                         */
/* -------------------------------------------------------------------------- */

type ButtonVariant = 'default' | 'outline' | 'danger' | 'panel'

export type ButtonSize = 'xxs' | 'xs' | 'sm' | 'base' | 'lg' | 'fit' | 'base-tall'

interface ButtonGroupContextValue {
    sizeContext: ButtonSize
    variantContext: ButtonVariant
}

const ButtonContext = createContext<ButtonGroupContextValue | null>(null)

function useButtonGroupContext(): ButtonGroupContextValue | null {
    const context = useContext(ButtonContext)
    return context
}

export type DisabledReasonsObject = Record<string, boolean>

type ButtonGroupProps = {
    children: ReactNode
    className?: string
    groupVariant?: ButtonVariant
} & VariantProps<typeof buttonPrimitiveVariants>

type ButtonBaseProps = {
    iconOnly?: boolean
    showDivider?: boolean
    disabled?: boolean
    // Like clsx, but for disabled reasons
    // Takes precedence over tooltip
    // Example: { 'Save the cohort first': isNewCohort, 'Cohort must be static to duplicate': !cohort.is_static }
    disabledReasons?: DisabledReasonsObject
    active?: boolean
    tooltip?: TooltipProps['title']
    tooltipDocLink?: TooltipProps['docLink']
    tooltipPlacement?: TooltipProps['placement']
    tooltipCloseDelayMs?: TooltipProps['closeDelayMs']
    tooltipVisible?: TooltipProps['visible']
    tooltipInteractive?: TooltipProps['interactive']
    buttonWrapper?: (button: JSX.Element) => JSX.Element
    // Like disabled but doesn't show the disabled state or focus state (still shows tooltip)
    inert?: boolean
    sceneShortcut?: SceneShortcutProps
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

export interface ButtonPrimitiveProps extends ButtonBaseProps, React.ButtonHTMLAttributes<HTMLButtonElement> {
    'data-attr'?: string
}

export const buttonPrimitiveVariants = cva({
    base: 'button-primitive group/button-primitive',
    variants: {
        variant: {
            // Bordereless variant (aka posthog tertiary button)
            default: 'button-primitive--variant-default',
            // Like default, but with a dark background (like active state by default)
            panel: 'button-primitive--variant-panel',
            // Bordereless danger variant (aka posthog danger tertiary button)
            danger: 'button-primitive--variant-danger',
            // Outline variant (aka posthog secondary button)
            outline: 'button-primitive--variant-outline',
        },
        size: {
            xxs: `button-primitive--size-xxs button-primitive--height-xxs text-sm`,
            xs: `button-primitive--size-xs button-primitive--height-xs text-sm`,
            sm: `button-primitive--size-sm button-primitive--height-sm text-sm`,
            base: `button-primitive--size-base button-primitive--height-base text-sm`,
            'base-tall': `button-primitive--size-base-tall button-primitive--height-base-tall text-sm`,
            lg: `button-primitive--size-lg button-primitive--height-lg text-base`,
            fit: 'px-0',
        },
        autoHeight: {
            true: 'button-primitive--height-auto h-auto',
            false: '',
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
            true: 'rounded button-primitive--full-width justify-start shrink-0 text-left',
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
        inert: {
            true: 'cursor-default hover:bg-inherit',
            false: '',
        },
        hasSideActionRight: {
            true: 'rounded',
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
        autoHeight: false,
    },
    compoundVariants: [
        {
            hasSideActionRight: true,
            size: 'sm',
            className: 'pr-[calc(var(--button-height-sm)+var(--button-padding-x-sm))]',
        },
        {
            hasSideActionRight: true,
            size: 'base',
            className: 'pr-[calc(var(--button-height-base)+var(--button-padding-x-base))]',
        },
        {
            hasSideActionRight: true,
            size: 'lg',
            className: 'pr-[calc(var(--button-height-lg)+var(--button-padding-x-lg))]',
        },
        {
            hasSideActionRight: true,
            menuItem: true,
            className: 'rounded',
        },
    ],
})

// Renders the list of disabled reasons if value is true, otherwise returns null
function renderDisabledReasons(disabledReasons: DisabledReasonsObject): JSX.Element | null {
    const reasons = Object.entries(disabledReasons)
        .filter(([_, value]) => value)
        .map(([reason]) => reason)

    if (!reasons.length) {
        return null
    }

    if (reasons.length === 1) {
        return <span>{reasons[0]}</span>
    }

    return (
        <>
            Disabled reasons:
            <ul className="pl-3 list-disc">
                {reasons.map((reason) => (
                    <li key={reason}>{reason}</li>
                ))}
            </ul>
        </>
    )
}

export const ButtonPrimitive = forwardRef<HTMLButtonElement, ButtonPrimitiveProps>((props, ref) => {
    const {
        className,
        variant,
        size = 'base',
        fullWidth,
        children,
        iconOnly,
        menuItem,
        disabled,
        disabledReasons,
        active,
        buttonWrapper,
        hasSideActionRight,
        isSideActionRight,
        tooltip,
        tooltipCloseDelayMs,
        tooltipPlacement,
        tooltipDocLink,
        tooltipVisible,
        tooltipInteractive,
        autoHeight,
        inert,
        sceneShortcut,
        ...rest
    } = props
    // If inside a ButtonGroup, use the context values, otherwise use props
    const context = useButtonGroupContext()
    const effectiveSize = context?.sizeContext || size
    const effectiveVariant = context?.variantContext || variant
    let effectiveDisabled = disabledReasons ? Object.values(disabledReasons).some((value) => value) : disabled

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
                    disabled: effectiveDisabled,
                    hasSideActionRight,
                    isSideActionRight,
                    autoHeight,
                    inert,
                    className,
                })
            ),
            ref,
            disabled: effectiveDisabled,
            ...rest,
            'aria-disabled': effectiveDisabled,
            'data-active': active,
            style: {
                '--button-height': `var(--button-icon-size-${effectiveSize})`,
            },
        },
        children
    )

    if (tooltip || tooltipDocLink || disabledReasons) {
        buttonComponent = (
            <Tooltip
                // If there are disabled reasons which are true, render them, otherwise render the tooltip
                title={
                    disabledReasons && Object.values(disabledReasons).some(Boolean)
                        ? renderDisabledReasons(disabledReasons)
                        : tooltip
                }
                placement={tooltipPlacement}
                closeDelayMs={tooltipCloseDelayMs}
                docLink={tooltipDocLink}
                visible={tooltipVisible}
                interactive={tooltipInteractive}
            >
                {buttonComponent}
            </Tooltip>
        )
    }

    if (buttonWrapper) {
        buttonComponent = buttonWrapper(buttonComponent)
    }

    if (sceneShortcut) {
        buttonComponent = <SceneShortcut {...sceneShortcut}>{buttonComponent}</SceneShortcut>
    }

    return buttonComponent
})

ButtonPrimitive.displayName = 'ButtonPrimitive'
