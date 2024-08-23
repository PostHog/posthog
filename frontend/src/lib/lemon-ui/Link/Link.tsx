import './Link.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { isExternalLink } from 'lib/utils'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { addProjectIdIfMissing } from 'lib/utils/router-utils'
import React from 'react'
import { useNotebookDrag } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'

import { sidePanelStateLogic, SidePanelTab } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'

import { IconOpenInNew } from '../icons'
import { Tooltip } from '../Tooltip'

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
    /** If true, the default color will be as normal text with only a link color on hover */
    subtle?: boolean
}

const shouldForcePageLoad = (input: any): boolean => {
    if (!input || typeof input !== 'string') {
        return false
    }

    // If the link is to a different team, force a page load to ensure the proper team switch happens
    const matches = input.match(/\/project\/(\d+)/)

    return !!matches && matches[1] !== `${getCurrentTeamId()}`
}

const isPostHogDomain = (url: string): boolean => {
    return /^https:\/\/((www|app|eu)\.)?posthog\.com/.test(url)
}

const isDirectLink = (url: string): boolean => {
    return /^(mailto:|https?:\/\/|:\/\/)/.test(url)
}

const isPostHogComDocs = (url: string): url is PostHogComDocsURL => {
    return /^https:\/\/(www\.)?posthog\.com\/docs/.test(url)
}

export type PostHogComDocsURL = `https://${'www.' | ''}posthog.com/docs/${string}`

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
            subtle,
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

        const { sidePanelOpen } = useValues(sidePanelStateLogic)
        const { openSidePanel } = useActions(sidePanelStateLogic)

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

            if (typeof to === 'string' && isPostHogComDocs(to)) {
                event.preventDefault()

                const target = event.currentTarget
                const container = document.getElementsByTagName('main')[0]
                const topBar = document.getElementsByClassName('TopBar3000')[0]
                if (!sidePanelOpen && container.contains(target)) {
                    setTimeout(() => {
                        // Little delay to allow the rendering of the side panel
                        const y = container.scrollTop + target.getBoundingClientRect().top - topBar.clientHeight
                        container.scrollTo({ top: y })
                    }, 50)
                }

                openSidePanel('docs', to)
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
        const href = to
            ? typeof to === 'string'
                ? isDirectLink(to) || disableClientSideRouting
                    ? to
                    : addProjectIdIfMissing(to)
                : '#'
            : undefined

        return to ? (
            // eslint-disable-next-line react/forbid-elements
            <a
                ref={ref as any}
                className={clsx('Link', subtle && 'Link--subtle', className)}
                onClick={onClick}
                href={href}
                target={target}
                rel={target === '_blank' ? rel : undefined}
                {...props}
                {...draggableProps}
            >
                {children}
                {targetBlankIcon && target === '_blank' ? <IconOpenInNew /> : null}
            </a>
        ) : (
            <Tooltip title={disabledReason ? <span className="italic">{disabledReason}</span> : undefined}>
                <span>
                    <button
                        ref={ref as any}
                        className={clsx('Link', subtle && 'Link--subtle', className)}
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
