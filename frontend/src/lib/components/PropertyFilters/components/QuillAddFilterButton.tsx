import { forwardRef } from 'react'

import { IconPlus } from '@posthog/icons'
import { Button, cn } from '@posthog/quill'

export interface QuillAddFilterButtonProps {
    label: string
    labelClassName?: string
    pageKey: string
    open: boolean
    onClick: () => void
}

export const QuillAddFilterButton = forwardRef<HTMLButtonElement, QuillAddFilterButtonProps>(
    function QuillAddFilterButton({ label, labelClassName, pageKey, open, onClick }, ref): JSX.Element {
        return (
            <Button
                ref={ref}
                variant="outline"
                onClick={onClick}
                className={cn('new-prop-filter', labelClassName)}
                data-attr={'new-prop-filter-' + pageKey}
                aria-expanded={open}
            >
                <IconPlus />
                {label}
            </Button>
        )
    }
)
