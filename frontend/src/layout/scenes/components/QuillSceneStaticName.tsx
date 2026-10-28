import { type ReactNode, useEffect, useRef, useState } from 'react'

import { Button, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

const COPIED_RESET_MS = 1500

export interface QuillSceneStaticNameProps {
    name: ReactNode
    icon?: ReactNode
    /** Shown as the name's tooltip instead of a line under the title. */
    description?: ReactNode
    className?: string
}

/**
 * A scene name nobody can rename, drawn like the trail's crumbs so the whole trail reads as one line. The scene
 * description moves into its tooltip. A plain text name copies to the clipboard on click, and the tooltip confirms it
 * in place instead of a toast. `QuillSceneTrail` renders it as its last crumb and owns its offsets.
 */
export function QuillSceneStaticName({ name, icon, description, className }: QuillSceneStaticNameProps): JSX.Element {
    const copyableName = typeof name === 'string' && name ? name : undefined
    const [copied, setCopied] = useState(false)
    // Clicking the trigger dismisses the tooltip, so it is controlled: `copied` holds it open over the dismissal
    // until the confirmation has had its moment.
    const [open, setOpen] = useState(false)
    const copiedTimeout = useRef<ReturnType<typeof setTimeout>>()
    useEffect(() => () => clearTimeout(copiedTimeout.current), [])

    const crumb = (
        <Button
            nativeButton={false}
            render={<h1 />}
            // Focusable to copy the name or to reach the tooltip, so keyboard users can do both.
            tabIndex={copyableName || description ? 0 : undefined}
            onClick={
                copyableName
                    ? async () => {
                          if (await copyToClipboard(copyableName, 'name', { silent: true })) {
                              setCopied(true)
                              clearTimeout(copiedTimeout.current)
                              copiedTimeout.current = setTimeout(() => setCopied(false), COPIED_RESET_MS)
                          }
                      }
                    : undefined
            }
            className={cn(
                'm-0 min-w-0 text-foreground',
                !copyableName && 'cursor-default hover:bg-transparent active:[translate:none]',
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

    if (!description && !copyableName) {
        return crumb
    }

    return (
        <Tooltip disableHoverablePopup open={open || copied} onOpenChange={setOpen}>
            <TooltipTrigger delay={300} render={crumb} />
            <TooltipContent className="max-w-80">
                {copied ? (
                    <div role="status">Copied</div>
                ) : (
                    <>
                        {description && <div>{description}</div>}
                        {copyableName && <div className="text-muted-foreground">Click to copy</div>}
                    </>
                )}
            </TooltipContent>
        </Tooltip>
    )
}
