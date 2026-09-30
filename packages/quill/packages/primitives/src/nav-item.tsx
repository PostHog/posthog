import './nav-item.css'

import { mergeProps } from '@base-ui/react/merge-props'
import { useRender } from '@base-ui/react/use-render'
import * as React from 'react'

import { buttonVariants } from './button'
import { cn } from './lib/utils'

// The action sits beside the button, not inside it, so a link row can still hold its own menu.
function NavItem({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return <div data-quill data-slot="nav-item" className={cn('quill-nav-item group/nav-item', className)} {...props} />
}

type NavItemButtonProps = useRender.ComponentProps<'button'> & {
    /** Marks the row as the page the user is on: `aria-current="page"` plus the selected fill. */
    current?: boolean
}

// useRender, not Base UI's Button, so `render={<Link />}` stays a plain link without button semantics.
const NavItemButton = React.forwardRef<HTMLButtonElement, NavItemButtonProps>(function NavItemButton(
    { current = false, className, render, ...props },
    ref
) {
    return useRender({
        ref,
        defaultTagName: 'button',
        props: mergeProps<'button'>(
            {
                'data-quill': '',
                'data-slot': 'nav-item-button',
                ...(render ? {} : { type: 'button' as const }),
                'aria-current': current ? 'page' : undefined,
                className: cn(
                    buttonVariants({
                        variant: 'default',
                        size: 'row',
                        left: true,
                    }),
                    'quill-nav-item__button',
                    className
                ),
            } as Omit<React.ComponentProps<'button'>, 'ref'>,
            props
        ),
        render,
    })
})

function NavItemLabel({ className, ...props }: React.ComponentProps<'span'>): React.ReactElement {
    return <span data-slot="nav-item-label" className={cn('min-w-0 flex-1 truncate', className)} {...props} />
}

function NavItemContent({ className, ...props }: React.ComponentProps<'span'>): React.ReactElement {
    return <span data-slot="nav-item-content" className={cn('flex min-w-0 flex-1 flex-col', className)} {...props} />
}

function NavItemDescription({ className, ...props }: React.ComponentProps<'span'>): React.ReactElement {
    return <span data-slot="nav-item-description" className={cn('quill-nav-item__description', className)} {...props} />
}

function NavItemMeta({ className, ...props }: React.ComponentProps<'span'>): React.ReactElement {
    return <span data-slot="nav-item-meta" className={cn('quill-nav-item__meta', className)} {...props} />
}

function NavItemAction({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return <div data-slot="nav-item-action" className={cn('quill-nav-item__action', className)} {...props} />
}

export { NavItem, NavItemButton, NavItemContent, NavItemDescription, NavItemLabel, NavItemMeta, NavItemAction }
export type { NavItemButtonProps }
