import * as TabsPrimitive from '@radix-ui/react-tabs'
import { cva } from 'cva'
import { cn } from 'lib/utils/css-classes'
import * as React from 'react'

const Tabs = TabsPrimitive.Root

const TabsList = React.forwardRef<
    React.ElementRef<typeof TabsPrimitive.List>,
    React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(({ className, ...props }, ref) => (
    <TabsPrimitive.List
        ref={ref}
        className={cn('flex gap-1 px-1 items-center border-b border-primary', className)}
        {...props}
    />
))
TabsList.displayName = TabsPrimitive.List.displayName

type TabsTriggerProps = React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger> & {
    variant?: 'default' | 'secondary'
}

const tabsTriggerVariants = cva({
    base: `
        text-secondary
        inline-flex
        items-center
        justify-center
        whitespace-nowrap
        rounded-md
        disabled:pointer-events-none
        disabled:opacity-50
        data-[state=active]:text-primary
        data-[state=active]:bg-fill-button-tertiary-active
    `,
    variants: {
        variant: {
            default: `
                not-disabled:hover:bg-transparent 
                data-[state=active]:bg-transparent 
                data-[state=active]:text-accent
                hover:text-accent
            `,
            secondary: `
                data-[state=active]:bg-fill-button-tertiary-active
            `,
        },
    },
    defaultVariants: {
        variant: 'default',
    },
})

const TabsTrigger = React.forwardRef<React.ElementRef<typeof TabsPrimitive.Trigger>, TabsTriggerProps>(
    ({ className, variant = 'default', ...props }, ref) => (
        <div>
            <TabsPrimitive.Trigger
                ref={ref}
                className={cn(
                    tabsTriggerVariants({
                        variant,
                    }),
                    'peer',
                    className
                )}
                {...props}
            />
            {variant === 'default' && (
                <div
                    aria-hidden="true"
                    className="
                    w-full
                    h-[2px]
                    opacity-0
                    bg-fill-highlight-100
                    peer-data-[state='active']:opacity-100
                    peer-data-[state='active']:bg-accent
                    peer-hover:opacity-100
                "
                />
            )}
        </div>
    )
)
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName

const TabsContent = React.forwardRef<
    React.ElementRef<typeof TabsPrimitive.Content>,
    React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(({ className, ...props }, ref) => (
    <TabsPrimitive.Content
        ref={ref}
        className={cn('mt-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2', className)}
        {...props}
    />
))
TabsContent.displayName = TabsPrimitive.Content.displayName

export {
    TabsContent as TabsContentPrimitive,
    TabsList as TabsListPrimitive,
    Tabs as TabsPrimitive,
    TabsTrigger as TabsTriggerPrimitive,
}
