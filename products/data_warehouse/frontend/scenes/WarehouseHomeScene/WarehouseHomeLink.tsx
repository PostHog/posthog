import posthog from 'posthog-js'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

// pinned: the analytics event name in this file feeds dashboards, so renaming it breaks them.

/** A link from the console overview to a console page. It records which section the click came from. */
export function WarehouseHomeLink({
    to,
    section,
    children,
    ...rest
}: {
    to: string
    section: string
    children: React.ReactNode
    className?: string
    'data-attr': string
}): JSX.Element {
    return (
        <LinkPrimitive to={to} onClick={() => posthog.capture('warehouse home link clicked', { section })} {...rest}>
            {children}
        </LinkPrimitive>
    )
}
