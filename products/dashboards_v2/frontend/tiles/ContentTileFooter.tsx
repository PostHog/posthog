import type { ReactNode } from 'react'

import { CardFooter } from '@posthog/quill'

export function ContentTileFooter({ children }: { children: ReactNode }): JSX.Element {
    return (
        // The grid's drag cancel selector lists this class, so a tile dragged by its body never starts a drag here.
        <CardFooter className="DashboardV2__footer flex shrink-0 items-center gap-2 min-w-0 text-xs text-secondary">
            {children}
        </CardFooter>
    )
}
