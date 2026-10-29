import type { ComponentProps, ReactNode } from 'react'

import { AutocompleteItem, Button, cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

export interface TodayPaneOptionProps extends Omit<
    ComponentProps<typeof AutocompleteItem>,
    'value' | 'render' | 'className' | 'children'
> {
    value: string
    to: string
    active: boolean
    variant?: 'default' | 'destructive'
    className?: string
    children: ReactNode
}

// Like Desktop's sidebar, the keyboard highlight tints the row like a hover, without a focus ring.
export function TodayPaneOption({
    value,
    to,
    active,
    variant = 'default',
    className,
    children,
    ...props
}: TodayPaneOptionProps): JSX.Element {
    return (
        <AutocompleteItem
            value={value}
            aria-current={active ? 'page' : undefined}
            data-variant={variant}
            {...props}
            render={
                <Button
                    size="row"
                    variant={variant}
                    left
                    nativeButton={false}
                    render={<LinkPrimitive to={to} />}
                    className={cn(
                        'w-full min-w-0 font-semibold [&>span]:w-full [&>span]:overflow-visible',
                        variant === 'default' && 'text-foreground',
                        'data-highlighted:border-transparent data-highlighted:ring-0',
                        active
                            ? 'bg-fill-selected data-highlighted:bg-fill-selected'
                            : 'data-highlighted:bg-fill-hover',
                        className
                    )}
                />
            }
        >
            {children}
        </AutocompleteItem>
    )
}
