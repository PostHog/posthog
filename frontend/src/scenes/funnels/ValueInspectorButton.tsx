import { forwardRef } from 'react'

import { Link } from '@posthog/lemon-ui'

interface ValueInspectorButtonProps {
    onClick?: (e?: React.MouseEvent) => void
    onMouseEnter?: (e?: React.MouseEvent) => void
    onMouseLeave?: (e?: React.MouseEvent) => void
    children: React.ReactNode
    title?: string | undefined
    'data-attr'?: string
}

export const ValueInspectorButton = forwardRef<HTMLElement, ValueInspectorButtonProps>(function ValueInspectorButton(
    { onClick, onMouseEnter, onMouseLeave, children, title, 'data-attr': dataAttr },
    ref
): JSX.Element {
    return onClick ? (
        <Link
            ref={ref}
            onClick={onClick}
            onMouseEnter={onMouseEnter}
            onMouseLeave={onMouseLeave}
            className="funnel-inspect-button"
            title={title}
            data-attr={dataAttr}
            subtle
        >
            {children}
        </Link>
    ) : (
        <span
            ref={ref}
            onMouseEnter={onMouseEnter}
            onMouseLeave={onMouseLeave}
            className="funnel-inspect-button"
            title={title}
            data-attr={dataAttr}
        >
            {children}
        </span>
    )
})
