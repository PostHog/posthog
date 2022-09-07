import React from 'react'
import { router } from 'kea-router'
import { isExternalLink } from 'lib/utils'

type RoutePart = string | Record<string, any>

export type LinkProps = Pick<
    React.HTMLProps<HTMLAnchorElement>,
    'target' | 'className' | 'onClick' | 'children' | 'title'
> & {
    to?: string | [string, RoutePart?, RoutePart?]
    preventClick?: boolean
}

/**
 * Link
 *
 * This component wraps an <a> element to ensure that proper tags are added related to target="_blank"
 * as well deciding when a given "to" link should be opened as a standard navigation (i.e. a standard href)
 * or whether to be routed internally via kea-router
 */
export function Link({ to, target, preventClick = false, ...props }: LinkProps): JSX.Element {
    const onClick = (event: React.MouseEvent<HTMLAnchorElement>): void => {
        if (event.metaKey || event.ctrlKey) {
            event.stopPropagation()
            return
        }

        if (!target && !isExternalLink(to)) {
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

    return (
        // eslint-disable-next-line react/forbid-elements
        <a
            {...props}
            href={typeof to === 'string' ? to : '#'}
            onClick={onClick}
            target={target}
            rel={target === '_blank' ? 'noopener noreferrer' : undefined}
        />
    )
}
