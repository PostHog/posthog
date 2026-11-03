import type { ReactNode } from 'react'

import { ButtonGroupText, buttonVariants, cn } from '@posthog/quill'

/**
 * The first segment of a chip that can't change what it filters on, such as a date range. It uses the disabled look of
 * the outline buttons beside it, so it doesn't read as clickable. The slot makes the group join it to its neighbors.
 */
export function FilterBarChipLabel({ children }: { children: ReactNode }): JSX.Element {
    return (
        <ButtonGroupText
            data-slot="button-group-text"
            aria-disabled="true"
            className={cn(buttonVariants({ variant: 'outline', inert: true }), 'min-w-0')}
        >
            {children}
        </ButtonGroupText>
    )
}
