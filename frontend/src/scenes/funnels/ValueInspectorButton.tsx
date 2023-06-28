import { Link } from '@posthog/lemon-ui'
import React from 'react'

interface ValueInspectorButtonProps {
    onClick?: (e?: React.MouseEvent) => void
    onMouseEnter?: (e?: React.MouseEvent) => void
    onMouseLeave?: (e?: React.MouseEvent) => void
    children: React.ReactNode
    title?: string | undefined
}

export const ValueInspectorButton = React.forwardRef<HTMLElement, ValueInspectorButtonProps>(
    ({ onClick, onMouseEnter, onMouseLeave, children, title }, ref) => {
        return onClick ? (
            <Link
                ref={ref}
                onClick={onClick}
                onMouseEnter={onMouseEnter}
                onMouseLeave={onMouseLeave}
                className="funnel-inspect-button"
                title={title}
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
            >
                {children}
            </span>
        )
    }
)
ValueInspectorButton.displayName = 'ValueInspectorButton'
