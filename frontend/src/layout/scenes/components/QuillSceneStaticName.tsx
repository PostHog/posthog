import type { ReactNode } from 'react'

import { Button, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

export interface QuillSceneStaticNameProps {
    name: ReactNode
    icon?: ReactNode
    /** Shown as the name's tooltip instead of a line under the title. */
    description?: ReactNode
    className?: string
}

/**
 * A scene name nobody can rename, drawn like the trail's crumbs so the whole trail reads as one line. The scene
 * description moves into its tooltip. `QuillSceneTrail` renders it as its last crumb and owns its offsets.
 */
export function QuillSceneStaticName({ name, icon, description, className }: QuillSceneStaticNameProps): JSX.Element {
    const crumb = (
        <Button
            nativeButton={false}
            render={<h1 />}
            // Focusable only to reach the tooltip, so keyboard users can read the description too.
            tabIndex={description ? 0 : undefined}
            className={cn(
                'm-0 min-w-0 cursor-default text-foreground hover:bg-transparent active:[translate:none]',
                className
            )}
            data-attr="scene-name"
        >
            {icon && (
                <span className="flex size-4 shrink-0 items-center justify-center [&_svg]:size-4" aria-hidden>
                    {icon}
                </span>
            )}
            <span className="truncate">{name}</span>
        </Button>
    )

    if (!description) {
        return crumb
    }

    return (
        <Tooltip disableHoverablePopup>
            <TooltipTrigger delay={300} render={crumb} />
            <TooltipContent className="max-w-80">{description}</TooltipContent>
        </Tooltip>
    )
}
