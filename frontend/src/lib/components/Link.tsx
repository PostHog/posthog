import React, { HTMLProps } from 'react'
import { router } from 'kea-router'

export interface LinkProps extends HTMLProps<HTMLAnchorElement> {
    to: string
    preventClick?: boolean
    tag?: string | React.Component
}

export function Link({ to, preventClick = false, tag = 'a', ...props }: LinkProps): JSX.Element {
    const onClick = (event: React.MouseEvent<HTMLAnchorElement>): void => {
        if (event.metaKey || event.ctrlKey) {
            event.stopPropagation()
            return
        }

        if (!props.target) {
            event.preventDefault()
            event.stopPropagation()
            if (to && to !== '#' && !preventClick) {
                router.actions.push(to) // router is mounted automatically, so this is safe to call
            }
        }
        props.onClick && props.onClick(event)
    }

    return React.createElement(tag, {
        href: to || '#',
        ...props,
        onClick,
    })
}
