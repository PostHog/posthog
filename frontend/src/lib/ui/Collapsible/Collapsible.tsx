import { cva } from 'cva'
import { createContext, forwardRef, useContext } from 'react'

import { IconChevronRight } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    CollapsiblePrimitive,
    CollapsiblePrimitiveContent,
    CollapsiblePrimitiveTrigger,
    type CollapsiblePrimitiveProps,
} from 'lib/ui/Collapsible/lib/CollapsiblePrimitive'
import { Label } from 'lib/ui/Label/Label'
import { cn } from 'lib/utils/css-classes'

/* --------------------------------- Context -------------------------------- */

type CollapsibleVariant = 'menu' | 'container'

const CollapsibleContext = createContext<{ variant: CollapsibleVariant }>({ variant: 'menu' })

function useCollapsibleVariant(): CollapsibleVariant {
    return useContext(CollapsibleContext).variant
}

/* ---------------------------------- Root ---------------------------------- */

export interface CollapsibleProps extends CollapsiblePrimitiveProps {
    variant?: CollapsibleVariant
}

function CollapsibleRoot({ variant = 'menu', children, ...rest }: CollapsibleProps): JSX.Element {
    return (
        <CollapsibleContext.Provider value={{ variant }}>
            <CollapsiblePrimitive {...rest}>{children}</CollapsiblePrimitive>
        </CollapsibleContext.Provider>
    )
}

/* --------------------------------- Trigger -------------------------------- */

const triggerVariants = cva({
    base: 'flex items-center w-full cursor-pointer',
    variants: {
        variant: {
            menu: 'py-1 group pl-2',
            container:
                'relative justify-start rounded-none h-full overflow-hidden disabled:opacity-60 text-xs p-0 px-2',
        },
    },
    defaultVariants: {
        variant: 'menu',
    },
})

export interface CollapsibleTriggerProps extends React.ComponentProps<typeof CollapsiblePrimitiveTrigger> {
    /** Only applies to the "menu" variant. Ignored for "container". */
    icon?: React.ReactNode
    /** Only applies to the "menu" variant. Ignored for "container". */
    labelClassName?: string
    /** Only applies to the "menu" variant. Ignored for "container". */
    hideChevron?: boolean
}

const CollapsibleTrigger = forwardRef<HTMLButtonElement, CollapsibleTriggerProps>(
    ({ icon, children, className, labelClassName, hideChevron, ...rest }, ref) => {
        const variant = useCollapsibleVariant()

        if (variant === 'menu') {
            return (
                <CollapsiblePrimitiveTrigger
                    ref={ref}
                    className={cn(triggerVariants({ variant: 'menu' }), className)}
                    {...rest}
                >
                    <Label
                        intent="menu"
                        className={cn('text-xxs text-tertiary text-left group-hover:text-primary mr-1', labelClassName)}
                    >
                        {icon && <span className="size-3 mr-1">{icon}</span>}
                        {children}
                    </Label>
                    {!hideChevron && (
                        <IconChevronRight
                            aria-hidden={true}
                            className="size-3 text-tertiary opacity-50 group-hover:opacity-100 transition-all duration-150 group-data-[panel-open]:rotate-90"
                        />
                    )}
                </CollapsiblePrimitiveTrigger>
            )
        }

        return (
            <CollapsiblePrimitiveTrigger
                ref={ref}
                render={<ButtonPrimitive />}
                className={cn(triggerVariants({ variant: 'container' }), className)}
                {...rest}
            >
                {children}
            </CollapsiblePrimitiveTrigger>
        )
    }
)
CollapsibleTrigger.displayName = 'CollapsibleTrigger'

/* ---------------------------------- Panel --------------------------------- */

const panelVariants = cva({
    variants: {
        variant: {
            menu: 'flex flex-col gap-px',
            container: 'border-t-1',
        },
    },
    defaultVariants: {
        variant: 'menu',
    },
})

export interface CollapsiblePanelProps extends React.ComponentProps<typeof CollapsiblePrimitiveContent> {}

const CollapsiblePanel = forwardRef<HTMLDivElement, CollapsiblePanelProps>(({ className, ...rest }, ref) => {
    const variant = useCollapsibleVariant()
    return <CollapsiblePrimitiveContent ref={ref} className={cn(panelVariants({ variant }), className)} {...rest} />
})
CollapsiblePanel.displayName = 'CollapsiblePanel'

/* --------------------------------- Export --------------------------------- */

export const Collapsible = Object.assign(CollapsibleRoot, {
    Trigger: CollapsibleTrigger,
    Panel: CollapsiblePanel,
})
