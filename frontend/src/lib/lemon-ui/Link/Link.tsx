import React from 'react'
import { router } from 'kea-router'
import { isExternalLink } from 'lib/utils'
import clsx from 'clsx'
import './Link.scss'
import { IconOpenInNew } from '../icons'
import { Tooltip } from '../Tooltip'
import { useNotebookDrag } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'

type RoutePart = string | Record<string, any>

export type LinkProps = Pick<React.HTMLProps<HTMLAnchorElement>, 'target' | 'className' | 'children' | 'title'> & {
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
    /** @deprecated Links should never be quietly disabled. Use `disabledReason` to provide an explanation instead. */
    disabled?: boolean
    /** Like plain `disabled`, except we enforce a reason to be shown in the tooltip. */
    disabledReason?: string | null | false
    /**
     * Whether an "open in new" icon should be shown if target is `_blank`.
     * This is true by default if `children` is a string.
     */
    targetBlankIcon?: boolean
}

// Some URLs we want to enforce a full reload such as billing which is redirected by Django
const FORCE_PAGE_LOAD = ['/billing/']

const shouldForcePageLoad = (input: any): boolean => {
    if (!input || typeof input !== 'string') {
        return false
    }
    return !!FORCE_PAGE_LOAD.find((x) => input.startsWith(x))
}

const isPostHogDomain = (url: string): boolean => {
    return /https:\/\/((app|eu)\.)?posthog\.com'/.test(url)
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
            disabled,
            disabledReason,
            targetBlankIcon = typeof children === 'string',
            ...props
        },
        ref
    ) => {
        const { elementProps: draggableProps } = useNotebookDrag({
            href: typeof to === 'string' ? to : undefined,
        })

        const onClick = (event: React.MouseEvent<HTMLElement>): void => {
            if (event.metaKey || event.ctrlKey) {
                event.stopPropagation()
                return
            }

            onClickRaw?.(event)

            if (event.isDefaultPrevented()) {
                event.preventDefault()
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
        }

        const rel = typeof to === 'string' && isPostHogDomain(to) ? 'noopener' : 'noopener noreferrer'

        return to ? (
            // eslint-disable-next-line react/forbid-elements
            <a
                ref={ref as any}
                className={clsx('Link', className)}
                onClick={onClick}
                href={typeof to === 'string' ? to : '#'}
                target={target}
                rel={target === '_blank' ? rel : undefined}
                {...props}
                {...draggableProps}
            >
                {children}
                {targetBlankIcon && target === '_blank' ? <IconOpenInNew /> : null}
            </a>
        ) : (
            <Tooltip
                isDefaultTooltip
                title={disabledReason ? <span className="italic">{disabledReason}</span> : undefined}
            >
                <span>
                    <button
                        ref={ref as any}
                        className={clsx('Link', className)}
                        onClick={onClick}
                        type="button"
                        disabled={disabled || !!disabledReason}
                        {...props}
                    >
                        {children}
                    </button>
                </span>
            </Tooltip>
        )
    }
)
Link.displayName = 'Link'
