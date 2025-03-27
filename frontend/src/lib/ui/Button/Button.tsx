import './Button.css'

import { cva, type VariantProps } from 'cva'
import { Link } from 'lib/lemon-ui/Link/Link'
import { cn } from 'lib/utils/css-classes'
import React, {
    ComponentPropsWithoutRef,
    createContext,
    ElementType,
    forwardRef,
    ReactNode,
    Ref,
    useContext,
    useState,
} from 'react'

/* -------------------------------------------------------------------------- */
/*                           Constants & Types                                */
/* -------------------------------------------------------------------------- */

const BUTTON_HEIGHT_SM = 'h-[var(--button-height-sm)]'
const BUTTON_ICON_WIDTH_SM = 'w-[var(--button-height-sm)]'
const BUTTON_HEIGHT_BASE = 'h-[var(--button-height-base)]'
const BUTTON_ICON_WIDTH_BASE = 'w-[var(--button-height-base)]'
const BUTTON_HEIGHT_LG = 'h-[var(--button-height-lg)]'
const BUTTON_ICON_WIDTH_LG = 'w-[var(--button-height-lg)]'

type ButtonIntent = 'default' | 'outline'

const BUTTON_INTENT: Record<ButtonIntent, string> = {
    default:
        'text-primary not-disabled:hover:bg-fill-highlight-100 data-[state=open]:bg-fill-highlight-50 data-[state=checked]:bg-fill-highlight-50',
    outline: 'text-primary border border-primary not-disabled:hover:border-tertiary hover:bg-fill-highlight-50',
}

export type ButtonSize = 'sm' | 'base' | 'lg'

/* -------------------------------------------------------------------------- */
/*                           Polymorphic Type Helpers                         */
/* -------------------------------------------------------------------------- */

type PolymorphicRef<E extends ElementType> = Ref<React.ElementRef<E>>

/**
 * PolymorphicComponentProps
 * - E extends ElementType: The HTML element or React component to render.
 * - P: Additional props specific to our custom component logic.
 */
type PolymorphicComponentProps<E extends ElementType, P> = P &
    Omit<ComponentPropsWithoutRef<E>, keyof P> & {
        as?: E
        children?: ReactNode
        ref?: PolymorphicRef<E>
    }

/* -------------------------------------------------------------------------- */
/*                           Button Context & Hook                            */
/* -------------------------------------------------------------------------- */

interface ButtonContextValue {
    sizeContext: ButtonSize
    intentContext: ButtonIntent
    setIsPressedContext: React.Dispatch<React.SetStateAction<boolean>>
}

const ButtonContext = createContext<ButtonContextValue | null>(null)

function useButtonContext(): ButtonContextValue {
    const context = useContext(ButtonContext)
    if (!context) {
        throw new Error('Button compound components must be used within <Button.Root>.')
    }
    return context
}

/* -------------------------------------------------------------------------- */
/*                              Button.Root                                   */
/* -------------------------------------------------------------------------- */

const buttonVariants = cva({
    base: `
        button-root
        group/button-root
        inline-flex 
        w-fit 
        items-center 
        justify-center 
        gap-1 
        px-[5px] 
        py-[3px] 
        rounded-md 
        transition-colors 
        duration-100
        cursor-default
    `,
    variants: {
        intent: {
            default: BUTTON_INTENT.default,
            outline: BUTTON_INTENT.outline,
        },
        size: {
            sm: 'px-[var(--button-padding-x-sm)] py-[var(--button-padding-y-sm)] ' + BUTTON_HEIGHT_SM,
            base: 'px-[var(--button-padding-x-base)] py-[var(--button-padding-y-base)] ' + BUTTON_HEIGHT_BASE,
            lg: 'px-[var(--button-padding-x-lg)] py-[var(--button-padding-y-lg)] ' + BUTTON_HEIGHT_LG,
        },
        fullWidth: {
            true: 'w-full',
            false: '',
        },
        menuItem: {
            true: 'w-full justify-start',
            false: '',
        },
        disabled: {
            true: 'opacity-50 cursor-default',
            false: '',
        },
        // empty
        active: {
            true: '',
            false: '',
        },
    },
    defaultVariants: {
        intent: 'default',
        size: 'base',
        disabled: false,
        active: false,
    },
})

export interface ButtonRootProps extends VariantProps<typeof buttonVariants> {
    // You can add your own custom props here, for instance "disabled?: boolean;"
    // We'll demonstrate a simple onClick approach
    onClick?: React.MouseEventHandler
    fullWidth?: boolean
    menuItem?: boolean
    to?: string
    disableClientSideRouting?: boolean
    targetBlank?: boolean
    disabled?: boolean
    /** Wrap the button component with a custom component. */
    buttonWrapper?: (button: JSX.Element) => JSX.Element
}

function ButtonRootComponent<E extends ElementType = 'button'>(
    {
        as,
        onClick,
        children,
        intent,
        size,
        className,
        fullWidth,
        menuItem,
        to,
        disabled,
        disableClientSideRouting,
        targetBlank,
        type,
        active,
        buttonWrapper,
        ...props
    }: PolymorphicComponentProps<E, ButtonRootProps>,
    forwardedRef: PolymorphicRef<E>
): JSX.Element {
    const [isPressed, setIsPressed] = useState(false)
    const Component = to ? Link : as || 'button'

    // Detect if the underlying element is actually a native <button>
    const isNativeButton = Component === 'button'

    // Optional: If rendering something else (like <div>), we add "button-like" accessibility
    const handleKeyDown = (e: React.KeyboardEvent): void => {
        // Only trigger if the key event happened on the parent (currentTarget),
        // not a nested child.
        if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) {
            e.preventDefault()
            onClick?.(e as unknown as React.MouseEvent<HTMLDivElement>)
        }
    }

    // If not a native button, add role, tabIndex=0, and handle keyboard activation
    const a11yProps = !isNativeButton
        ? {
              role: menuItem ? 'menuitem' : 'button',
              tabIndex: 0,
              onKeyDown: handleKeyDown,
          }
        : {}

    const linkProps = to
        ? {
              role: menuItem ? 'menuitem' : 'link',
              disableClientSideRouting,
              target: targetBlank ? '_blank' : undefined,
              to: !disabled ? to : undefined,
          }
        : { type: type }

    const handleMouseDown = (): void => setIsPressed(true)
    const handleMouseUp = (): void => setIsPressed(false)

    const contextValue = {
        isPressedContext: isPressed,
        setIsPressedContext: setIsPressed,
        sizeContext: size || 'base',
        intentContext: intent || 'default',
    }

    let buttonComponent = (
        <Component
            ref={forwardedRef}
            onMouseDown={handleMouseDown}
            onMouseUp={handleMouseUp}
            onClick={onClick}
            className={cn(buttonVariants({ intent, size, fullWidth, menuItem, disabled, active }), className)}
            // Used to identify the current item in a set of items
            aria-current={active ? 'true' : 'false'}
            // Used to identify disabled items
            aria-disabled={disabled}
            // Used to identify pressed state
            aria-pressed={isPressed}
            {...a11yProps}
            {...linkProps}
            {...props}
        >
            {children}
        </Component>
    )

    if (buttonWrapper) {
        buttonComponent = buttonWrapper(buttonComponent)
    }

    return <ButtonContext.Provider value={contextValue}>{buttonComponent}</ButtonContext.Provider>
}

/**
 * Wrap in forwardRef and type-assert so we can preserve the polymorphic signature.
 */
const ButtonRoot = forwardRef(ButtonRootComponent) as <E extends ElementType = 'button'>(
    props: PolymorphicComponentProps<E, ButtonRootProps>
) => JSX.Element

/* -------------------------------------------------------------------------- */
/*                              Button.Icon                                   */
/* -------------------------------------------------------------------------- */

const iconVariants = cva({
    base: `
        flex
        items-center
        justify-center
        relative
        first:-mr-[2px]
        first:-ml-1
        last:-mr-1
        last:-ml-[2px]
        shrink-0
        transition-all
        duration-100
        rounded-md
    `,
    variants: {
        intent: {
            default: '',
            outline: '',
        },
        size: {
            sm: 'size-5 only:-mx-[2px]',
            base: 'size-6 only:-mx-[7px]',
            lg: 'size-7 only:-mx-[9px]',
        },
        customIconSize: {
            true: '',
            false: '',
        },
        isTrigger: {
            true: `
                first:mr-1 first:rounded-l-md first:rounded-r-none
                last:ml-1 last:rounded-r-md last:rounded-l-none
            `,
            false: '',
        },
        showTriggerDivider: {
            true: '',
            false: '',
        },
    },
    compoundVariants: [
        // Icon sizes
        {
            customIconSize: false,
            size: 'sm',
            className: '[&_svg]:size-3',
        },
        {
            customIconSize: false,
            size: 'base',
            className: '[&_svg]:size-4',
        },
        {
            customIconSize: false,
            size: 'lg',
            className: '[&_svg]:size-5',
        },

        // Only if trigger does it have styles
        {
            intent: 'default',
            isTrigger: true,
            className: `
                ${BUTTON_INTENT.default}
                hover:bg-fill-highlight-100
            `,
        },
        {
            intent: 'outline',
            isTrigger: true,
            className: `
                ${BUTTON_INTENT.outline}
                hover:bg-fill-highlight-100
                first:before:hidden
                last:after:hidden
            `,
        },

        // Icon match the button height
        {
            size: 'sm',
            isTrigger: true,
            className: `
                first:ml-[calc(var(--button-padding-x-sm)*-1-1px)] 
                last:mr-[calc(var(--button-padding-x-sm)*-1-1px)] 
                ${BUTTON_HEIGHT_SM} 
                ${BUTTON_ICON_WIDTH_SM}
            `,
        },
        {
            size: 'base',
            isTrigger: true,
            className: `
                first:ml-[calc(var(--button-padding-x-base)*-1-1px)] 
                last:mr-[calc(var(--button-padding-x-base)*-1-1px)]  
                ${BUTTON_HEIGHT_BASE} 
                ${BUTTON_ICON_WIDTH_BASE}
            `,
        },
        {
            size: 'lg',
            isTrigger: true,
            className: `
                first:ml-[calc(var(--button-padding-x-lg)*-1-1px)] 
                last:mr-[calc(var(--button-padding-x-lg)*-1-1px)] 
                ${BUTTON_HEIGHT_LG} 
                ${BUTTON_ICON_WIDTH_LG}
            `,
        },
        // Give a border to the icon when it's a trigger
        // Initial styles
        {
            isTrigger: true,
            showTriggerDivider: true,
            className: `
                first:before:content-[''] first:before:absolute first:before:h-full first:before:w-px first:before:bg-fill-highlight-100
                last:after:content-[''] last:after:absolute last:after:h-full last:after:w-px last:after:bg-fill-highlight-100
            `,
        },
        // Trigger divider styles by size
        {
            size: 'sm',
            isTrigger: true,
            showTriggerDivider: true,
            className: `
                first:before:left-[var(--button-height-sm)]
                
                last:after:right-[var(--button-height-sm)]
            `,
        },
        {
            size: 'base',
            isTrigger: true,
            showTriggerDivider: true,
            className: `
                first:before:left-[var(--button-height-base)]
                last:after:right-[var(--button-height-base)]
            `,
        },
        {
            size: 'lg',
            isTrigger: true,
            showTriggerDivider: true,
            className: `
                first:before:left-[var(--button-height-lg)]
                last:after:right-[var(--button-height-lg)]
            `,
        },
    ],
    defaultVariants: {
        intent: 'default',
        size: 'base',
    },
})

interface ButtonIconProps extends VariantProps<typeof iconVariants> {
    isTrigger?: boolean
    showTriggerDivider?: boolean
}

function ButtonIconComponent<E extends ElementType = 'span'>(
    {
        as,
        children,
        size,
        intent,
        isTrigger,
        customIconSize = false,
        showTriggerDivider = false,
        ...props
    }: PolymorphicComponentProps<E, ButtonIconProps>,
    forwardedRef: PolymorphicRef<E>
): JSX.Element {
    const { sizeContext, intentContext } = useButtonContext()
    const Component = as || 'span'

    return (
        <Component
            {...(props as any)}
            ref={forwardedRef as any}
            className={cn(
                iconVariants({
                    size: size || sizeContext,
                    intent: intent || intentContext,
                    isTrigger,
                    customIconSize,
                    showTriggerDivider,
                })
            )}
            tabIndex={isTrigger ? 0 : undefined}
            aria-hidden={!isTrigger}
        >
            {children}
        </Component>
    )
}

const ButtonIcon = forwardRef(ButtonIconComponent) as <E extends ElementType = 'span'>(
    props: PolymorphicComponentProps<E, ButtonIconProps> & { ref?: PolymorphicRef<E> }
) => JSX.Element

/* -------------------------------------------------------------------------- */
/*                              Button.Label                                  */
/* -------------------------------------------------------------------------- */

const buttonLabelVariants = cva({
    base: `
        select-none
    `,
    variants: {
        size: {
            sm: 'text-xs',
            base: 'text-sm',
            lg: 'text-base',
        },
        menuItem: {
            true: 'flex w-full items-center justify-between',
            false: '',
        },
        truncate: {
            true: 'truncate',
            false: '',
        },
    },
    defaultVariants: {
        size: 'base',
    },
})

interface ButtonLabelProps extends VariantProps<typeof buttonLabelVariants> {
    menuItem?: boolean
    className?: string
    truncate?: boolean
}

function ButtonLabelComponent<E extends ElementType = 'span'>(
    { as, children, size, menuItem, truncate, ...props }: PolymorphicComponentProps<E, ButtonLabelProps>,
    forwardedRef: PolymorphicRef<E>
): JSX.Element {
    const Component = as || 'span'

    return (
        <Component
            {...(props as any)}
            ref={forwardedRef as any}
            className={cn(buttonLabelVariants({ size, menuItem, truncate }), props.className)}
        >
            {children}
        </Component>
    )
}

const ButtonLabel = forwardRef(ButtonLabelComponent) as <E extends ElementType = 'span'>(
    props: PolymorphicComponentProps<E, ButtonLabelProps> & { ref?: PolymorphicRef<E> }
) => JSX.Element

/* -------------------------------------------------------------------------- */
/*                             Export as Button                               */
/* -------------------------------------------------------------------------- */

export const Button = {
    Root: ButtonRoot,
    Icon: ButtonIcon,
    Label: ButtonLabel,
}
