import './tabs.css'

import { Tabs as TabsPrimitive } from '@base-ui/react/tabs'
import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import { Button } from './button'
import { cn } from './lib/utils'

/**
 * Groups the tabs and the corresponding panels.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Tabs](https://base-ui.com/react/components/tabs)
 *
 * @baseui Tabs.Root
 */
function Tabs({ className, orientation = 'horizontal', ...props }: TabsPrimitive.Root.Props): React.ReactElement {
    return (
        <TabsPrimitive.Root
            data-slot="tabs"
            data-orientation={orientation}
            className={cn('group/tabs flex gap-2 data-[orientation=horizontal]:flex-col', className)}
            {...props}
        />
    )
}

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

/**
 * Groups the individual tab buttons.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Tabs](https://base-ui.com/react/components/tabs)
 *
 * @baseui Tabs.List
 */
function TabsList({
    className,
    variant = 'default',
    ...props
}: TabsPrimitive.List.Props & VariantProps<typeof tabsListVariants>): React.ReactElement {
    return (
        <TabsPrimitive.List
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
}

/**
 * An individual interactive tab button that toggles the corresponding panel.
 * Renders a `<button>` element.
 *
 * Documentation: [Base UI Tabs](https://base-ui.com/react/components/tabs)
 *
 * @baseui Tabs.Tab
 */
function TabsTrigger({ className, ...props }: TabsPrimitive.Tab.Props): React.ReactElement {
    return (
        <TabsPrimitive.Tab
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

/**
 * A panel displayed when the corresponding tab is active.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Tabs](https://base-ui.com/react/components/tabs)
 *
 * @baseui Tabs.Panel
 */
function TabsContent({ className, ...props }: TabsPrimitive.Panel.Props): React.ReactElement {
    return <TabsPrimitive.Panel data-slot="tabs-content" className={cn('quill-tabs__panel', className)} {...props} />
}

export { Tabs, TabsList, TabsTrigger, TabsContent, tabsListVariants }
