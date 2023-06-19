import { LemonButton } from '@posthog/lemon-ui'
import React from 'react'

interface ValueInspectorButtonProps {
    icon?: JSX.Element
    onClick: (e?: React.MouseEvent) => void
    onMouseEnter?: (e?: React.MouseEvent) => void
    onMouseLeave?: (e?: React.MouseEvent) => void
    children: React.ReactNode
    disabled?: boolean
    title?: string | undefined
}

export const ValueInspectorButton = React.forwardRef<HTMLAnchorElement, ValueInspectorButtonProps>(
    ({ icon, onClick, onMouseEnter, onMouseLeave, children, disabled, title }, ref) => {
        return (
            <LemonButton
                ref={ref}
                type="link"
                icon={icon}
                onClick={onClick}
                onMouseEnter={onMouseEnter}
                onMouseLeave={onMouseLeave}
                className="funnel-inspect-button"
                disabled={disabled}
                title={title}
            >
                <span className="funnel-inspect-label">{children}</span>
            </LemonButton>
        )
    }
)
ValueInspectorButton.displayName = 'ValueInspectorButton'
