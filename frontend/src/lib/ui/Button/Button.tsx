import './Button.css'

import { cva, type VariantProps } from 'cva'
import { Link, LinkProps } from 'lib/lemon-ui/Link/Link'
import { cn } from 'lib/utils/css-classes'
import React, { createContext, forwardRef, ReactNode, useContext } from 'react'

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
            ring ring-transparent
            text-primary 
            max-w-full
            not-disabled:hover:bg-fill-button-tertiary-hover 
            data-[focused=true]:bg-fill-button-tertiary-hover 
            data-[active=true]:bg-fill-button-tertiary-active 
            data-[current=true]:bg-fill-button-tertiary-active 
            data-[state=open]:bg-fill-button-tertiary-active 
            data-[state=checked]:bg-fill-button-tertiary-active
            
        `,
    outline: 'ring ring-secondary not-disabled:hover:ring-tertiary hover:bg-fill-button-tertiary-active',
}

export type ButtonSize = 'sm' | 'base' | 'lg'

/* -------------------------------------------------------------------------- */
/*                           Button Context & Hook                            */
/* -------------------------------------------------------------------------- */

interface ButtonContextValue {
    sizeContext: ButtonSize
    intentContext: ButtonIntent
    rootLinkProps?: LinkProps
    onClick?: React.MouseEventHandler
    onKeyDown?: React.KeyboardEventHandler
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
        rounded-md 
        cursor-default
    `,
    variants: {
        intent: {
            default: BUTTON_INTENT.default,
            outline: BUTTON_INTENT.outline,
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
        disabled: false,
    },
})

export interface ButtonRootProps extends VariantProps<typeof buttonVariants> {
    fullWidth?: boolean
    menuItem?: boolean
    size?: ButtonSize
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
    linkProps?: LinkProps
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
            disabled,
            active,
            current,
            buttonWrapper,
            linkProps,
            menuItem,
            ...props
        }: ButtonRootProps,
        ref: React.ForwardedRef<HTMLButtonElement>
    ): JSX.Element => {
        // const linkProps = to
        //     ? {
        //         role: menuItem ? 'menuitem' : 'link',
        //         disableClientSideRouting,
        //         target: targetBlank ? '_blank' : undefined,
        //         to: !disabled ? to : undefined,
        //     }
        //     : undefined

        const contextValue: ButtonContextValue = {
            sizeContext: size || 'base',
            intentContext: intent || 'default',
            // We pass the link props to the label so it can be used as a link
            rootLinkProps: linkProps,
            ...props,
        }

        let buttonComponent = (
            <span
                ref={ref}
                className={cn(buttonVariants({ intent, fullWidth, disabled, menuItem }), className, 'z-1')}
                // Used to identify the current item in a set of items
                aria-current={current ? 'true' : 'false'}
                // Used to identify active items in a set of items
                data-active={active}
                // Used to identify disabled items
                aria-disabled={disabled}
                // Root is focusable by default
                tabIndex={0}
                // Root is a button by default
                role="button"
                {...props}
            >
                {children}
            </span>
        )

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
        text-current
    `,
    variants: {
        intent: {
            default: '',
            outline: '',
        },
        size: {
            sm: 'size-5',
            base: 'size-6',
            lg: 'size-7',
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
        start: {
            true: '',
            false: '',
        },
        end: {
            true: '',
            false: '',
        },
    },
    compoundVariants: [
        // Icon sizes
        {
            customIconSize: false,
            size: 'sm',
            className: 'size-[var(--button-height-sm)] [&_svg]:size-3',
        },
        {
            customIconSize: false,
            size: 'base',
            className: 'size-[var(--button-height-base)] [&_svg]:size-4',
        },
        {
            customIconSize: false,
            size: 'lg',
            className: 'size-[var(--button-height-lg)] [&_svg]:size-5',
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

        // {
        //     start: true,
        //     size: 'sm',
        //     className: `
        //         pl-[var(--button-padding-x-sm)]
        //     `,
        // },
        // {
        //     start: true,
        //     size: 'base',
        //     className: `
        //         pl-[var(--button-padding-x-base)]
        //     `,
        // },
        // {
        //     start: true,
        //     size: 'lg',
        //     className: `
        //         pl-[var(--button-padding-x-lg)]
        //     `,
        // },
        // {
        //     end: true,
        //     size: 'sm',
        //     className: `
        //         pr-[var(--button-padding-x-sm)]
        //     `,
        // },
        // {
        //     end: true,
        //     size: 'base',
        //     className: `
        //         pr-[var(--button-padding-x-base)]
        //     `,
        // },
        // {
        //     end: true,
        //     size: 'lg',
        //     className: `                pr-[var(--button-padding-x-lg)]
        //     `,
        // },

        // Give a border to the icon when it's a trigger
        // Initial styles
        // {
        //     isTrigger: true,
        //     showTriggerDivider: true,
        //     className: `
        //         first:before:content-[''] first:before:absolute first:before:h-full first:before:w-px first:before:bg-fill-highlight-100
        //         last:after:content-[''] last:after:absolute last:after:h-full last:after:w-px last:after:bg-fill-highlight-100
        //         first:before:left-full
        //         last:after:right-full
        //     `,
        // },
    ],
    defaultVariants: {
        intent: 'default',
        size: 'base',
    },
})

interface ButtonIconProps extends VariantProps<typeof iconVariants> {
    className?: string
    children: ReactNode
    start?: boolean
    end?: boolean
}

const ButtonIcon = forwardRef(
    (
        { children, size, intent, isTrigger, customIconSize = false, className, start, end, ...props }: ButtonIconProps,
        ref: React.ForwardedRef<HTMLSpanElement>
    ): JSX.Element => {
        const { sizeContext, intentContext } = useButtonContext()

        return (
            <span
                ref={ref}
                className={cn(
                    iconVariants({
                        size: size || sizeContext,
                        intent: intent || intentContext,
                        isTrigger,
                        customIconSize,
                        showTriggerDivider: false,
                        start,
                        end,
                        className,
                    }),
                    className
                )}
                {...props}
            >
                {children}
            </span>
        )
    }
)

ButtonIcon.displayName = 'Button.Icon'

/* -------------------------------------------------------------------------- */
/*                              Button.IconLink                                */
/* -------------------------------------------------------------------------- */

interface ButtonIconLinkProps extends ButtonIconProps, Omit<LinkProps, 'children' | 'subtle'> {
    showTriggerDivider?: boolean
}

const ButtonIconLink = forwardRef(
    (
        {
            children,
            size,
            intent,
            customIconSize = false,
            showTriggerDivider = false,
            className,
            start,
            end,
            ...props
        }: ButtonIconLinkProps,
        ref: React.ForwardedRef<HTMLAnchorElement>
    ): JSX.Element => {
        const { sizeContext, intentContext } = useButtonContext()

        return (
            <Link
                ref={ref}
                className={cn(
                    iconVariants({
                        size: size || sizeContext,
                        intent: intent || intentContext,
                        isTrigger: true,
                        customIconSize,
                        showTriggerDivider,
                        start,
                        end,
                        className,
                    }),
                    className
                )}
                {...props}
            >
                {children}
            </Link>
        )
    }
)

ButtonIconLink.displayName = 'Button.IconLink'

/* -------------------------------------------------------------------------- */
/*                              Button.IconButton                             */
/* -------------------------------------------------------------------------- */

interface ButtonIconButtonProps extends Omit<ButtonIconProps, 'isTrigger'> {
    showTriggerDivider?: boolean
    onClick?: React.MouseEventHandler
    onKeyDown?: React.KeyboardEventHandler
}

const ButtonIconButton = forwardRef(
    (
        {
            children,
            size,
            intent,
            customIconSize = false,
            showTriggerDivider = false,
            className,
            start,
            end,
            ...props
        }: ButtonIconButtonProps,
        ref: React.ForwardedRef<HTMLButtonElement>
    ): JSX.Element => {
        const { sizeContext, intentContext } = useButtonContext()

        return (
            <button
                ref={ref}
                className={cn(
                    iconVariants({
                        size: size || sizeContext,
                        intent: intent || intentContext,
                        isTrigger: true,
                        customIconSize,
                        showTriggerDivider,
                        start,
                        end,
                        className,
                    }),
                    className
                )}
                {...props}
            >
                {children}
            </button>
        )
    }
)

ButtonIconButton.displayName = 'Button.IconButton'

/* -------------------------------------------------------------------------- */
/*                              Button.Label                                  */
/* -------------------------------------------------------------------------- */

const buttonLabelVariants = cva({
    base: `
        button-label block select-none text-current
    `,
    variants: {
        size: {
            sm: 'text-xs px-[var(--button-padding-x-sm)] py-[var(--button-padding-y-sm)] ' + BUTTON_HEIGHT_SM,
            base: 'text-sm px-[var(--button-padding-x-base)] py-[var(--button-padding-y-base)] ' + BUTTON_HEIGHT_BASE,
            lg: 'text-base px-[var(--button-padding-x-lg)] py-[var(--button-padding-y-lg)] ' + BUTTON_HEIGHT_LG,
        },
        menuItem: {
            true: 'text-left w-full',
            false: '',
        },
        truncate: {
            true: 'block truncate',
            false: '',
        },
        iconLeft: {
            true: 'pl-0',
            false: '',
        },
        iconRight: {
            true: 'pr-0',
            false: '',
        },
    },
    defaultVariants: {
        size: 'base',
        menuItem: false,
    },
})

interface ButtonLabelProps extends VariantProps<typeof buttonLabelVariants> {
    menuItem?: boolean
    className?: string
    truncate?: boolean
    disableClientSideRouting?: boolean
    targetBlank?: boolean
    children: ReactNode
    iconLeft?: boolean
    iconRight?: boolean
}

const ButtonLabel = forwardRef(
    (
        {
            children,
            menuItem,
            truncate,
            disableClientSideRouting,
            targetBlank,
            className,
            iconLeft,
            iconRight,
            ...props
        }: ButtonLabelProps,
        ref: React.ForwardedRef<HTMLButtonElement>
    ): JSX.Element => {
        const { sizeContext, rootLinkProps, onClick } = useButtonContext()

        const Component = rootLinkProps ? Link : 'button'

        const linkProps = rootLinkProps
            ? {
                  role: 'link',
                  disableClientSideRouting,
                  target: targetBlank ? '_blank' : undefined,
                  ...rootLinkProps,
              }
            : undefined

        return (
            <Component
                ref={ref}
                className={cn(
                    buttonLabelVariants({
                        size: sizeContext,
                        menuItem,
                        truncate,
                        iconLeft,
                        iconRight,
                        className,
                    })
                )}
                // We take root onClick and put it on label
                onClick={onClick}
                // Label is not focusable by default
                tabIndex={-1}
                {...linkProps}
                {...props}
            >
                {children}
            </Component>
        )
    }
)

ButtonLabel.displayName = 'Button.Label'

/* -------------------------------------------------------------------------- */
/*                             Export as Button                               */
/* -------------------------------------------------------------------------- */

export const Button = {
    Root: ButtonRoot,
    Icon: ButtonIcon,
    Label: ButtonLabel,
    IconLink: ButtonIconLink,
    IconButton: ButtonIconButton,
}
