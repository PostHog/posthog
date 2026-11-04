import { ReactNode } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { Button, cn } from '@posthog/quill'

interface ChecksToggleButtonProps {
    expanded: boolean
    controlsId: string
    subjectName: string
    onToggle: () => void
    dataAttr: string
    children: ReactNode
}

export function ChecksToggleButton({
    expanded,
    controlsId,
    subjectName,
    onToggle,
    dataAttr,
    children,
}: ChecksToggleButtonProps): JSX.Element {
    return (
        <Button
            size="xs"
            aria-expanded={expanded}
            aria-controls={controlsId}
            aria-label={`${expanded ? 'Hide' : 'Show'} checks for ${subjectName}`}
            className="-ml-1.5 gap-1"
            onClick={onToggle}
            data-attr={dataAttr}
        >
            {children}
            <IconChevronRight
                aria-hidden
                className={cn('size-3 transition-transform motion-reduce:transition-none', expanded && 'rotate-90')}
            />
        </Button>
    )
}
