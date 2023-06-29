import React from 'react'
import { router } from 'kea-router'
import { isExternalLink } from 'lib/utils'
import clsx from 'clsx'
import './Link.scss'
import { IconOpenInNew } from '../icons'

type RoutePart = string | Record<string, any>

export type LinkProps = Pick<
    React.HTMLProps<HTMLAnchorElement>,
    'target' | 'className' | 'children' | 'title' | 'disabled'
> & {
    /** The location to go to. This can be a kea-location or a "href"-like string */
    to?: string | [string, RoutePart?, RoutePart?]
    /** If true, in-app navigation will not be used and the link will navigate with a page load */
    disableClientSideRouting?: boolean
    preventClick?: boolean
    onClick?: (event: React.MouseEvent<HTMLElement>) => void
    onMouseDown?: (event: React.MouseEvent<HTMLElement>) => void
    onMouseEnter?: (event: React.MouseEvent<HTMLElement>) => void
    onMouseLeave?: (event: React.MouseEvent<HTMLElement>) => void
    onKeyDown?: (event: React.KeyboardEvent<HTMLElement>) => void
    onFocus?: (event: React.FocusEvent<HTMLElement>) => void
}

// Some URLs we want to enforce a full reload such as billing which is redirected by Django
const FORCE_PAGE_LOAD = ['/billing/']

const shouldForcePageLoad = (input: any): boolean => {
    if (!input || typeof input !== 'string') {
        return false
    }
    return !!FORCE_PAGE_LOAD.find((x) => input.startsWith(x))
}

/**
 * Link
 *
 * This component wraps an <a> element to ensure that proper tags are added related to target="_blank"
 * as well deciding when a given "to" link should be opened as a standard navigation (i.e. a standard href)
 * or whether to be routed internally via kea-router
 */
export const Link: React.FC<LinkProps & React.RefAttributes<HTMLElement>> = React.forwardRef(
    (
        {
            to,
            target,
            disableClientSideRouting,
            preventClick = false,
            onClick: onClickRaw,
            className,
            children,
            ...props
        },
        ref
    ) => {
        const onClick = (event: React.MouseEvent<HTMLElement>): void => {
            if (event.metaKey || event.ctrlKey) {
                event.stopPropagation()
                return
            }

            if (!target && to && !isExternalLink(to) && !disableClientSideRouting && !shouldForcePageLoad(to)) {
                event.preventDefault()
                if (to && to !== '#' && !preventClick) {
                    if (Array.isArray(to)) {
                        router.actions.push(...to)
                    } else {
                        router.actions.push(to)
                    }
                }
            }
            onClickRaw?.(event)
        }

        return to ? (
            <a
                ref={ref as any}
                className={clsx('Link', className)}
                onClick={onClick}
                href={typeof to === 'string' ? to : '#'}
                target={target}
                rel={target === '_blank' ? 'noopener noreferrer' : undefined}
                {...props}
            >
                {children}
                {typeof children === 'string' && target === '_blank' ? <IconOpenInNew /> : null}
            </a>
        ) : (
            <button ref={ref as any} className={clsx('Link', className)} onClick={onClick} type="button" {...props}>
                {children}
            </button>
        )
    }
)
Link.displayName = 'Link'
