import './Link.scss'

import { router } from 'kea-router'
import React from 'react'

import { IconExternal, IconSend } from '@posthog/icons'

import { ButtonPrimitiveProps, buttonPrimitiveVariants } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { addProjectIdIfMissing, removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { isExternalLink } from 'lib/utils/url'
import { useNotebookDrag } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'
import { urlToResource } from 'scenes/urls'

import { Tooltip, TooltipProps } from '../Tooltip'

type RoutePart = string | Record<string, any>

/**
 * Behavior-only props — the routing surface shared by `LinkPrimitive` and `Link`.
 */
export type LinkPrimitiveProps = Pick<
    React.HTMLProps<HTMLAnchorElement>,
    'target' | 'className' | 'children' | 'title'
> & {
    /** The location to go to. This can be a kea-location or a "href"-like string */
    to?: string | [string, RoutePart?, RoutePart?]
    /** If true, in-app navigation will not be used and the link will navigate with a page load */
    disableClientSideRouting?: boolean
    preventClick?: boolean
    onClick?: (event: React.MouseEvent<HTMLElement>) => void
    onAuxClick?: (event: React.MouseEvent<HTMLElement>) => void
    onDoubleClick?: (event: React.MouseEvent<HTMLElement>) => void
    onMouseDown?: (event: React.MouseEvent<HTMLElement>) => void
    onMouseEnter?: (event: React.MouseEvent<HTMLElement>) => void
    onMouseLeave?: (event: React.MouseEvent<HTMLElement>) => void
    onKeyDown?: (event: React.KeyboardEvent<HTMLElement>) => void
    onFocus?: (event: React.FocusEvent<HTMLElement>) => void
    /** Disables the rendered control. Only meaningful with no `to` (renders a `<button>`). */
    disabled?: boolean
    /** Accessibility role of the link. */
    role?: string
    /** Accessibility tab index of the link. */
    tabIndex?: number
}

export type LinkProps = LinkPrimitiveProps & {
    /** If true, docs links will not be opened in the docs panel */
    disableDocsPanel?: boolean
    /** Like plain `disabled`, except we enforce a reason to be shown in the tooltip. */
    disabledReason?: string | null | false
    /**
     * Whether an "open in new" icon should be shown if target is `_blank`.
     * This is true by default if `children` is a string.
     */
    targetBlankIcon?: boolean
    /** If true, the default color will be as normal text with only a link color on hover */
    subtle?: boolean

    /**
     * Button props to pass to the button primitive.
     * If provided, the link will be rendered as the "new" button primitive.
     *
     * @deprecated `buttonProps` renders via the legacy button primitive, which is being
     * phased out. For a link styled as a quill button, render a `LinkPrimitive` as the
     * `render` target of quill's `Button`: `<Button render={<LinkPrimitive to="…" />}>`.
     */
    buttonProps?: Omit<ButtonPrimitiveProps, 'tooltip' | 'tooltipDocLink' | 'tooltipPlacement' | 'children'>

    /** @deprecated WARNING, tooltip prop on Link breaks the auto-show of subsequent tooltips. Use Tooltip component instead for long lists that require tooltips. */
    tooltip?: TooltipProps['title']
    tooltipDocLink?: TooltipProps['docLink']
    tooltipPlacement?: TooltipProps['placement']
    tooltipCloseDelayMs?: TooltipProps['closeDelayMs']
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

const hasDangerousScheme = (url: string): boolean => {
    // Browsers ignore leading control chars/whitespace and any tabs/newlines embedded in the scheme,
    // so strip them all before matching. javascript:/vbscript: targets must never become an href —
    // not even when disableClientSideRouting would otherwise skip the routing rewrite.
    const normalized = url.replace(/[\u0000-\u0020]/g, '').toLowerCase()
    return /^(javascript|vbscript):/.test(normalized)
}

/** Resolve a `to` target into a concrete href string. */
function resolveHref(to: LinkPrimitiveProps['to'], disableClientSideRouting?: boolean): string | undefined {
    if (!to) {
        return undefined
    }
    if (typeof to !== 'string') {
        return '#'
    }
    if (hasDangerousScheme(to)) {
        return '#'
    }
    return isDirectLink(to) || disableClientSideRouting ? to : addProjectIdIfMissing(to)
}

export type PostHogComDocsURL = `https://${'www.' | ''}posthog.com/docs/${string}`

/**
 * LinkPrimitive — styling-neutral routing core.
 *
 * Owns only href resolution and kea-router navigation, and renders a bare `<a>`
 * (or a bare `<button>` when there's no `to`). It adds NO cosmetic styling, no
 * external-link icon, and no Tooltip / ContextMenu wrappers.
 *
 * Use it as the `render` target of a styled control so the two concerns compose
 * cleanly — e.g. `<Button render={<LinkPrimitive to="…" />}>`: quill's `Button`
 * supplies styling (and `data-quill`), `LinkPrimitive` supplies navigation.
 *
 * For a standalone, cosmetically-styled text link, use `Link` instead.
 */
export const LinkPrimitive: React.FC<LinkPrimitiveProps & React.RefAttributes<HTMLElement>> = React.forwardRef(
    (
        {
            to,
            target,
            disableClientSideRouting,
            preventClick = false,
            onClick: onClickRaw,
            onAuxClick,
            className,
            children,
            disabled,
            role,
            tabIndex,
            ...props
        },
        ref
    ) => {
        const externalLink = isExternalLink(to)
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

            if (!target && to && !externalLink && !disableClientSideRouting && !shouldForcePageLoad(to)) {
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

        if (!to) {
            return (
                <button
                    ref={ref as any}
                    className={className}
                    onClick={onClick}
                    type="button"
                    disabled={disabled}
                    {...props}
                >
                    {children}
                </button>
            )
        }

        const rel = typeof to === 'string' && isPostHogDomain(to) ? 'noopener' : 'noopener noreferrer'
        const href = resolveHref(to, disableClientSideRouting)
        const resource = href && href.startsWith('/') ? urlToResource(removeProjectIdIfPresent(href)) : null

        return (
            // eslint-disable-next-line react/forbid-elements
            <a
                ref={ref as any}
                className={className}
                onClick={onClick}
                onAuxClick={onAuxClick}
                href={href}
                target={target}
                rel={target === '_blank' ? rel : undefined}
                role={role}
                tabIndex={tabIndex}
                {...props}
                {...draggableProps}
                {...(resource ? { 'data-resource-type': resource.type, 'data-resource-ref': resource.ref } : undefined)}
            >
                {children}
            </a>
        )
    }
)
LinkPrimitive.displayName = 'LinkPrimitive'

/**
 * Link
 *
 * A standalone, cosmetically-styled text link. Layers the `.Link` look (and the
 * external-link icon, auto Tooltip, and right-click ContextMenu) on top of
 * `LinkPrimitive`, which does the actual href resolution and routing.
 *
 * For a link that should look like a button, do NOT use `Link` — render a
 * `LinkPrimitive` inside quill's `Button` (see `LinkPrimitive` docs).
 */
export const Link: React.FC<LinkProps & React.RefAttributes<HTMLElement>> = React.forwardRef(
    (
        {
            to,
            target,
            subtle,
            disableClientSideRouting,
            disableDocsPanel: _disableDocsPanel,
            preventClick = false,
            onClick: onClickRaw,
            onAuxClick,
            className,
            children,
            disabled,
            disabledReason,
            targetBlankIcon = typeof children === 'string',
            buttonProps,
            tooltip,
            tooltipDocLink,
            tooltipPlacement,
            tooltipCloseDelayMs,
            role,
            tabIndex,
            ...props
        },
        ref
    ) => {
        const href = resolveHref(to, disableClientSideRouting)

        const elementClasses = buttonProps
            ? buttonPrimitiveVariants(buttonProps)
            : `Link ${subtle ? 'Link--subtle' : ''}`

        let element = (
            <LinkPrimitive
                ref={ref}
                to={to}
                target={target}
                disableClientSideRouting={disableClientSideRouting}
                preventClick={preventClick}
                onClick={onClickRaw}
                onAuxClick={onAuxClick}
                className={cn(elementClasses, className)}
                disabled={disabled || !!disabledReason}
                role={role}
                tabIndex={tabIndex}
                {...props}
            >
                {children}
                {targetBlankIcon &&
                    (href?.startsWith('mailto:') ? (
                        <IconSend />
                    ) : target === '_blank' ? (
                        <IconExternal className={buttonProps ? 'size-3' : ''} />
                    ) : null)}
            </LinkPrimitive>
        )

        // Wrap with tooltip first (before context menu) so trigger props can be applied to the element
        if ((tooltip && to) || tooltipDocLink) {
            element = (
                <Tooltip
                    title={tooltip}
                    docLink={tooltipDocLink}
                    placement={tooltipPlacement}
                    closeDelayMs={tooltipCloseDelayMs}
                >
                    {element}
                </Tooltip>
            )
        }

        if (!to) {
            element = (
                <Tooltip
                    title={disabledReason ? <span className="italic">{disabledReason}</span> : tooltip || undefined}
                    placement={tooltipPlacement}
                    closeDelayMs={tooltipCloseDelayMs}
                >
                    <span>{element}</span>
                </Tooltip>
            )
        }

        return element
    }
)
Link.displayName = 'Link'
