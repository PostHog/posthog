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
    default: `
            border border-transparent
            text-primary 
            not-disabled:hover:bg-fill-button-tertiary-hover 
            data-[focused=true]:bg-fill-button-tertiary-hover 
            data-[active=true]:bg-fill-button-tertiary-active 
            data-[current=true]:bg-fill-button-tertiary-active 
            data-[state=open]:bg-fill-button-tertiary-active 
            data-[state=checked]:bg-fill-button-tertiary-active
            
        `,
    outline: 'border border-secondary not-disabled:hover:border-tertiary hover:bg-fill-button-tertiary-active',
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
        relative
        inline-flex 
        w-fit 
        items-center 
        justify-center 
        gap-1.5 
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
    },
    defaultVariants: {
        intent: 'default',
        size: 'base',
        disabled: false,
    },
})

export interface ButtonRootProps extends VariantProps<typeof buttonVariants> {
    fullWidth?: boolean
    menuItem?: boolean
    to?: string
    disableClientSideRouting?: boolean
    targetBlank?: boolean
    disabled?: boolean
    // Active item in a set of items
    active?: boolean
    // Current item in a set of items
    current?: boolean
    /** Wrap the button component with a custom component. */
    buttonWrapper?: (button: JSX.Element) => JSX.Element

    role?: string
    tabIndex?: number
    children: ReactNode
    className?: string
    onClick?: React.MouseEventHandler
    onKeyDown?: React.KeyboardEventHandler
}

const ButtonRoot = forwardRef(
    (
        {
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
            active,
            current,
            buttonWrapper,
            ...props
        }: ButtonRootProps,
        ref: React.ForwardedRef<HTMLButtonElement>
    ): JSX.Element => {
        // const [isPressed, setIsPressed] = useState(false)
        // const Component = as || 'button'

        const linkProps = to
            ? {
                  role: menuItem ? 'menuitem' : 'link',
                  disableClientSideRouting,
                  target: targetBlank ? '_blank' : undefined,
                  to: !disabled ? to : undefined,
              }
            : undefined

        const contextValue = {
            sizeContext: size || 'base',
            intentContext: intent || 'default',
        }

        let buttonComponent: JSX.Element

        if (to) {
            buttonComponent = (
                <Link
                    ref={ref}
                    className={cn(buttonVariants({ intent, size, fullWidth, menuItem, disabled }), className)}
                    disableClientSideRouting={disableClientSideRouting}
                    target={targetBlank ? '_blank' : undefined}
                    to={!disabled ? to : undefined}
                    {...props}
                >
                    {children}
                </Link>
            )
        } else {
            buttonComponent = (
                <button
                    ref={ref}
                    className={cn(buttonVariants({ intent, size, fullWidth, menuItem, disabled }), className)}
                    // Used to identify the current item in a set of items
                    aria-current={current ? 'true' : 'false'}
                    // Used to identify active items in a set of items
                    data-active={active}
                    // Used to identify disabled items
                    aria-disabled={disabled}
                    {...linkProps}
                    {...props}
                >
                    {children}
                </button>
            )
        }

        if (buttonWrapper) {
            buttonComponent = buttonWrapper(buttonComponent)
        }

        return <ButtonContext.Provider value={contextValue}>{buttonComponent}</ButtonContext.Provider>
    }
)

ButtonRoot.displayName = 'Button.Root'

/* -------------------------------------------------------------------------- */
/*                              Button.Icon                                   */
/* -------------------------------------------------------------------------- */

const iconVariants = cva({
    base: `
        flex
        items-center
        justify-center
        relative
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
            sm: 'size-5 only:-mx-[calc(var(--button-padding-x-sm)/2)]',
            base: 'size-6 only:-mx-[calc(var(--button-padding-x-base)/2+1px)]',
            lg: 'size-7 only:-mx-[calc(var(--button-padding-x-lg)/2-1px)]',
        },
        customIconSize: {
            true: '',
            false: '',
        },
        isTrigger: {
            true: `
                first:rounded-l-md first:rounded-r-none
                last:rounded-r-md last:rounded-l-none
            `,
            false: '',
        },
        showTriggerDivider: {
            true: '',
            false: '',
        },
        isTriggerLeft: {
            true: '',
            false: '',
        },
        isTriggerRight: {
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
                ${BUTTON_HEIGHT_SM} 
                ${BUTTON_ICON_WIDTH_SM}
            `,
        },
        {
            size: 'base',
            isTrigger: true,
            className: `
                ${BUTTON_HEIGHT_BASE} 
                ${BUTTON_ICON_WIDTH_BASE}
            `,
        },
        {
            size: 'lg',
            isTrigger: true,
            className: `
                ${BUTTON_HEIGHT_LG} 
                ${BUTTON_ICON_WIDTH_LG}
            `,
        },

        // Compensate for button padding
        {
            size: 'sm',
            isTrigger: true,
            isTriggerLeft: true,
            className: `
                -ml-[calc(var(--button-padding-x-sm)+1px)]
            `,
        },
        {
            size: 'sm',
            isTrigger: true,
            isTriggerRight: true,
            className: `
                -mr-[calc(var(--button-padding-x-sm)+1px)]
            `,
        },
        {
            size: 'base',
            isTrigger: true,
            isTriggerLeft: true,
            className: `
                -ml-[calc(var(--button-padding-x-base)+1px)]
            `,
        },
        {
            size: 'base',
            isTrigger: true,
            isTriggerRight: true,
            className: `
                -mr-[calc(var(--button-padding-x-base)+1px)]
            `,
        },
        {
            size: 'lg',
            isTrigger: true,
            isTriggerLeft: true,
            className: `
                -ml-[calc(var(--button-padding-x-lg)+1px)]
            `,
        },
        {
            size: 'lg',
            isTrigger: true,
            isTriggerRight: true,
            className: `
                -mr-[calc(var(--button-padding-x-lg)+1px)]
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
                first:before:left-full
                last:after:right-full
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
    to?: string
    disableClientSideRouting?: boolean
    targetBlank?: boolean
    className?: string
    isTriggerLeft?: boolean
    isTriggerRight?: boolean
    onClick?: React.MouseEventHandler
    onKeyDown?: React.KeyboardEventHandler
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
        to,
        disableClientSideRouting,
        targetBlank,
        className,
        isTriggerLeft,
        isTriggerRight,
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
                    isTriggerLeft,
                    isTriggerRight,
                }),
                className
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
            true: 'block truncate text-left w-full',
            false: '',
        },
        truncate: {
            true: 'block truncate',
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
    disableClientSideRouting?: boolean
    targetBlank?: boolean
    onClick?: React.MouseEventHandler
}

function ButtonLabelComponent<E extends ElementType = 'span'>(
    {
        as,
        children,
        size,
        menuItem,
        truncate,
        to,
        disableClientSideRouting,
        targetBlank,
        ...props
    }: PolymorphicComponentProps<E, ButtonLabelProps>,
    forwardedRef: PolymorphicRef<E>
): JSX.Element {
    const Component = to ? Link : as || 'span'

    const linkProps = to
        ? {
              role: 'link',
              disableClientSideRouting,
              target: targetBlank ? '_blank' : undefined,
          }
        : {}

    return (
        <Component
            ref={forwardedRef as any}
            className={cn('button-label', buttonLabelVariants({ size, menuItem, truncate }), props.className)}
            {...(props as any)}
            {...linkProps}
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
