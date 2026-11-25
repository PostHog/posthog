import posthog from 'posthog-js'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

// pinned: the data-attr values and analytics event name in this file feed autocapture and dashboards, so renaming them breaks both.

/** A plain link on the explainer that records which page it opens. */
export function WarehouseExplainerLink({
    to,
    target,
    children,
}: {
    to: string
    target: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <LinkPrimitive
            to={to}
            className="text-sm underline"
            onClick={() => posthog.capture('warehouse explainer link clicked', { target })}
            data-attr={`warehouse-explainer-link-${target}`}
        >
            {children}
        </LinkPrimitive>
    )
}
