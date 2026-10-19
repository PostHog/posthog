import './tabs.css'

import { Tabs as TabsPrimitive } from '@base-ui/react/tabs'
import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import { Button } from './button'
import { cn } from './lib/utils'

const Tabs = React.forwardRef<React.ComponentRef<typeof TabsPrimitive.Root>, TabsPrimitive.Root.Props>(function Tabs(
    { className, orientation = 'horizontal', ...props },
    ref
) {
    return (
        <TabsPrimitive.Root
            ref={ref}
            data-slot="tabs"
            data-orientation={orientation}
            className={cn('group/tabs flex gap-2 data-[orientation=horizontal]:flex-col', className)}
            {...props}
        />
    )
})

const tabsListVariants = cva(
    'quill-tabs__list group/tabs-list inline-flex w-fit items-center justify-center relative',
    {
        variants: {
            variant: {
                default: 'quill-tabs__list--variant-default',
                line: 'quill-tabs__list--variant-line',
            },
        },
        defaultVariants: {
            variant: 'default',
        },
    }
)

const tabsIndicatorVariants = cva('quill-tabs__indicator', {
    variants: {
        variant: {
            default: 'quill-tabs__indicator--variant-default',
            line: 'quill-tabs__indicator--variant-line',
        },
    },
    defaultVariants: {
        variant: 'default',
    },
})

const TabsList = React.forwardRef<
    React.ComponentRef<typeof TabsPrimitive.List>,
    TabsPrimitive.List.Props & VariantProps<typeof tabsListVariants>
>(function TabsList({ className, variant = 'default', ...props }, ref) {
    return (
        <TabsPrimitive.List
            ref={ref}
            data-quill
            data-slot="tabs-list"
            data-variant={variant}
            className={cn(tabsListVariants({ variant }), className)}
            {...props}
        >
            {props.children}
            <TabsPrimitive.Indicator className={tabsIndicatorVariants({ variant })} />
        </TabsPrimitive.List>
    )
})

const TabsTrigger = React.forwardRef<React.ComponentRef<typeof TabsPrimitive.Tab>, TabsPrimitive.Tab.Props>(
    function TabsTrigger({ className, ...props }, ref) {
        return (
            <TabsPrimitive.Tab
                ref={ref}
                data-slot="tabs-trigger"
                className={cn(
                    'quill-tabs__trigger inline-flex items-center justify-center gap-1.5 whitespace-nowrap',
                    className
                )}
                {...props}
                render={(props) => <Button {...props} />}
            />
        )
    }
)

const TabsContent = React.forwardRef<React.ComponentRef<typeof TabsPrimitive.Panel>, TabsPrimitive.Panel.Props>(
    function TabsContent({ className, ...props }, ref) {
        return (
            <TabsPrimitive.Panel
                ref={ref}
                data-slot="tabs-content"
                className={cn('quill-tabs__panel', className)}
                {...props}
            />
        )
    }
)

export { Tabs, TabsList, TabsTrigger, TabsContent, tabsListVariants }
