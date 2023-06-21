import { Link } from '@posthog/lemon-ui'
import React from 'react'

interface ValueInspectorButtonProps {
    onClick: (e?: React.MouseEvent) => void
    onMouseEnter?: (e?: React.MouseEvent) => void
    onMouseLeave?: (e?: React.MouseEvent) => void
    children: React.ReactNode
    disabled?: boolean
    title?: string | undefined
}

export const ValueInspectorButton = React.forwardRef<HTMLAnchorElement, ValueInspectorButtonProps>(
    ({ onClick, onMouseEnter, onMouseLeave, children, disabled, title }, ref) => {
        return (
            <Link
                ref={ref}
                onClick={onClick}
                onMouseEnter={onMouseEnter}
                onMouseLeave={onMouseLeave}
                className="funnel-inspect-button"
                disabled={disabled}
                title={title}
            >
                {children}
            </Link>
        )
    }
)
ValueInspectorButton.displayName = 'ValueInspectorButton'
