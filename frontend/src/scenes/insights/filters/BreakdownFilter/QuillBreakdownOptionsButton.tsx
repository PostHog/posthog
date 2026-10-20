import { forwardRef } from 'react'

import { IconGear } from '@posthog/icons'

import { QuillIconButton } from 'lib/components/QuillIconButton/QuillIconButton'

export interface QuillBreakdownOptionsButtonProps {
    open: boolean
    onClick: () => void
}

export const QuillBreakdownOptionsButton = forwardRef<HTMLButtonElement, QuillBreakdownOptionsButtonProps>(
    function QuillBreakdownOptionsButton({ open, onClick }, ref): JSX.Element {
        return (
            <QuillIconButton
                ref={ref}
                label="Breakdown options"
                icon={<IconGear />}
                aria-expanded={open}
                onClick={onClick}
            />
        )
    }
)
