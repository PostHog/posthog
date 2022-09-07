import React from 'react'
import { router } from 'kea-router'
import { isExternalLink } from 'lib/utils'

type RoutePart = string | Record<string, any>

export interface LinkProps extends React.HTMLProps<HTMLAnchorElement> {
    to?: string | [string, RoutePart?, RoutePart?]
    preventClick?: boolean
    tag?: string | React.FunctionComponentElement<any>
}

// Some URLs we want to enforce a full reload such as billing which is redirected by Django
const FORCE_PAGE_LOAD = ['/billing/']

const shouldForcePageLoad = (input: any): boolean => {
    if (!input || typeof input !== 'string') {
        return false
    }
    return !!FORCE_PAGE_LOAD.find((x) => input.startsWith(x))
}

export function Link({ to, href, preventClick = false, tag = 'a', ...props }: LinkProps): JSX.Element {
    const onClick = (event: React.MouseEvent<HTMLAnchorElement>): void => {
        if (event.metaKey || event.ctrlKey) {
            event.stopPropagation()
            return
        }

        if (!props.target && to && !isExternalLink(to) && !shouldForcePageLoad(to)) {
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
        ...props,
        href: to || href || '#',
        onClick,
    }

    if (typeof tag === 'string') {
        return React.createElement(tag, elProps)
    } else {
        return React.cloneElement(tag, elProps)
    }
}
