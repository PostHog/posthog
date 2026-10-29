import type { ReactNode } from 'react'

import { IconEllipsis } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from '@posthog/quill'

interface SceneTitleSecondaryActionsProps {
    /** The secondary actions as buttons, for a wide scene */
    children: ReactNode
    /** The same actions as menu items, for a narrow scene */
    menu: ReactNode
}

/**
 * The secondary title actions under the Today layout. A narrow scene keeps only the primary action in view and moves
 * these into a "More actions" menu, so the title actions do not run into the scene menu bar.
 */
export function SceneTitleSecondaryActions({ children, menu }: SceneTitleSecondaryActionsProps): JSX.Element {
    return (
        <>
            <div className="flex items-center gap-1 @max-5xl/main-content:hidden">{children}</div>
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={
                        <Button
                            variant="outline"
                            size="icon"
                            aria-label="More actions"
                            className="hidden @max-5xl/main-content:inline-flex"
                            data-attr="scene-title-more-actions"
                        />
                    }
                >
                    <IconEllipsis className="rotate-90" />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">{menu}</DropdownMenuContent>
            </DropdownMenu>
        </>
    )
}
