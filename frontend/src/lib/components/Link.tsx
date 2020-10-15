import React, { HTMLProps } from 'react'
import { router } from 'kea-router'

interface LinkProps extends HTMLProps<HTMLAnchorElement> {
    to: string | [string, string?, string?]
    preventClick: boolean
    tag: string | React.Component
}

export function Link({ to, preventClick = false, tag = 'a', ...props }: LinkProps): JSX.Element {
    const onClick = (event): void => {
        if (event.metaKey || event.ctrlKey) {
            event.preventDefault()
            event.stopPropagation()
            return window.open(to, '_blank')
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
