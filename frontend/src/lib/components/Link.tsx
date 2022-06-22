import React from 'react'
import { router } from 'kea-router'
import { isExternalLink } from 'lib/utils'

type RoutePart = string | Record<string, any>

export interface LinkProps extends React.HTMLProps<HTMLAnchorElement> {
    to?: string | [string, RoutePart?, RoutePart?]
    preventClick?: boolean
    tag?: string | React.FunctionComponentElement<any>
}

export function Link({ to, preventClick = false, tag = 'a', ...props }: LinkProps): JSX.Element {
    const onClick = (event: React.MouseEvent<HTMLAnchorElement>): void => {
        if (event.metaKey || event.ctrlKey) {
            event.stopPropagation()
            return
        }

        if (!props.target && !isExternalLink(to)) {
            event.preventDefault()
            if (to && to !== '#' && !preventClick) {
                if (Array.isArray(to)) {
                    router.actions.push(...to)
                } else {
                    router.actions.push(to)
                }
            }
        }
        props.onClick?.(event)
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
