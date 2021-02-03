import React from 'react'
import { router } from 'kea-router'

export interface LinkProps extends React.HTMLProps<HTMLAnchorElement> {
    to: string
    preventClick?: boolean
    tag?: string | React.ReactNode
}

export function Link({ to, preventClick = false, tag = 'a', ...props }: LinkProps): JSX.Element {
    const onClick = (event: React.MouseEvent<HTMLAnchorElement>): void => {
        if (event.metaKey || event.ctrlKey) {
            event.stopPropagation()
            return
        }

        if (!props.target) {
            event.preventDefault()
            if (to && to !== '#' && !preventClick) {
                router.actions.push(to) // router is mounted automatically, so this is safe to call
            }
        }
        props.onClick && props.onClick(event)
    }

    return React.createElement(tag as string, {
        href: to || '#',
        ...props,
        onClick,
    })
}
