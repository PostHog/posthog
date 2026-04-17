import { Tabs as TabsPrimitive } from '@base-ui/react/tabs'
import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import { Button } from './button'
import { cn } from './lib/utils'

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
    'group/tabs-list z-0 inline-flex w-fit items-center relative justify-center rounded-lg p-[3px] text-muted-foreground group-data-[orientation=horizontal]/tabs:h-[calc(28px+(3.5px*2))] group-data-[orientation=vertical]/tabs:h-fit group-data-[orientation=vertical]/tabs:flex-col data-[variant=line]:rounded-none',
    {
        variants: {
            variant: {
                default: 'bg-accent',
                line: 'gap-1 bg-transparent',
            },
        },
        defaultVariants: {
            variant: 'default',
        },
    }
)

const tabsIndicatorVariants = cva('absolute transition-all duration-200 ease-in-out', {
    variants: {
        variant: {
            default:
                'z-[-1] rounded-sm bg-background group-data-[orientation=horizontal]/tabs:top-1/2 group-data-[orientation=horizontal]/tabs:left-0 group-data-[orientation=horizontal]/tabs:h-7 group-data-[orientation=horizontal]/tabs:w-[var(--active-tab-width)] group-data-[orientation=horizontal]/tabs:translate-x-[var(--active-tab-left)] group-data-[orientation=horizontal]/tabs:-translate-y-1/2 group-data-[orientation=vertical]/tabs:left-1/2 group-data-[orientation=vertical]/tabs:top-0 group-data-[orientation=vertical]/tabs:w-[calc(100%-6px)] group-data-[orientation=vertical]/tabs:h-[var(--active-tab-height)] group-data-[orientation=vertical]/tabs:translate-y-[var(--active-tab-top)] group-data-[orientation=vertical]/tabs:-translate-x-1/2',
            line: 'z-0 bg-foreground group-data-[orientation=horizontal]/tabs:bottom-0 group-data-[orientation=horizontal]/tabs:left-0 group-data-[orientation=horizontal]/tabs:h-0.5 group-data-[orientation=horizontal]/tabs:w-[var(--active-tab-width)] group-data-[orientation=horizontal]/tabs:translate-x-[var(--active-tab-left)] group-data-[orientation=vertical]/tabs:top-0 group-data-[orientation=vertical]/tabs:right-0 group-data-[orientation=vertical]/tabs:w-0.5 group-data-[orientation=vertical]/tabs:h-[var(--active-tab-height)] group-data-[orientation=vertical]/tabs:translate-y-[var(--active-tab-top)]',
        },
    },
    defaultVariants: {
        variant: 'default',
    },
})

function TabsList({
    className,
    variant = 'default',
    ...props
}: TabsPrimitive.List.Props & VariantProps<typeof tabsListVariants>): React.ReactElement {
    return (
        <TabsPrimitive.List
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

function TabsTrigger({ className, ...props }: TabsPrimitive.Tab.Props): React.ReactElement {
    return (
        <TabsPrimitive.Tab
            data-slot="tabs-trigger"
            className={cn(
                "relative inline-flex h-[calc(100%-1px)] flex-1 items-center justify-center gap-1.5 rounded-md border border-transparent px-1.5 py-0.5 text-xs font-medium whitespace-nowrap text-foreground/60 transition-all group-data-[orientation=vertical]/tabs:w-full group-data-[orientation=vertical]/tabs:justify-start group-data-[orientation=vertical]/tabs:py-[calc(--spacing(1.25))] hover:text-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-1 focus-visible:outline-ring disabled:pointer-events-none disabled:opacity-50 aria-disabled:pointer-events-none aria-disabled:opacity-50 dark:text-muted-foreground dark:hover:text-foreground [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
                'z-1 data-active:text-foreground hover:bg-transparent data-active:hover:bg-transparent data-active:active:translate-y-0',
                className
            )}
            {...props}
            render={(props) => <Button {...props} />}
        />
    )
}

function TabsContent({ className, ...props }: TabsPrimitive.Panel.Props): React.ReactElement {
    return (
        <TabsPrimitive.Panel
            data-slot="tabs-content"
            className={cn('flex-1 text-xs/relaxed outline-none', className)}
            {...props}
        />
    )
}

export { Tabs, TabsList, TabsTrigger, TabsContent, tabsListVariants }
