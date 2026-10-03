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
    className?: string
    children: ReactNode
}

// Like Desktop's sidebar, the keyboard highlight tints the row like a hover, without a focus ring.
export function TodayPaneOption({
    value,
    to,
    active,
    className,
    children,
    ...props
}: TodayPaneOptionProps): JSX.Element {
    return (
        <AutocompleteItem
            value={value}
            aria-current={active ? 'page' : undefined}
            {...props}
            render={
                <Button
                    size="row"
                    left
                    nativeButton={false}
                    render={<LinkPrimitive to={to} />}
                    className={cn(
                        'w-full min-w-0 text-foreground [&>span]:w-full',
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
