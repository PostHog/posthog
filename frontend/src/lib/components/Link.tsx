import React from 'react'
import { router } from 'kea-router'

export interface LinkProps extends React.HTMLProps<HTMLAnchorElement> {
    to: string
    preventClick?: boolean
    tag?: string | React.FunctionComponentElement<any>
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

    const elProps = {
        href: to || '#',
        ...props,
        onClick,
    }

    if (typeof tag === 'string') {
        return React.createElement(tag, elProps)
    } else {
        return React.cloneElement(tag, elProps)
    }
}
