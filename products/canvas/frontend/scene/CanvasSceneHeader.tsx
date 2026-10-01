import { useActions, useValues } from 'kea'
import { ChangeEvent, KeyboardEvent, useState } from 'react'

import { IconCopy, IconEllipsis, IconPencil, IconTrash } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Heading,
    Input,
    Skeleton,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { CanvasBuildStatusBadge } from './CanvasBuildStatusBadge'
import { canvasSceneLogic } from './canvasSceneLogic'

function CanvasNameInput({ name }: { name: string }): JSX.Element {
    const { savingName } = useValues(canvasSceneLogic)
    const { renameCanvas, setRenaming } = useActions(canvasSceneLogic)
    const [draft, setDraft] = useState(name)

    return (
        <form
            className="min-w-0 flex-1"
            onSubmit={(event) => {
                event.preventDefault()
                renameCanvas(draft)
            }}
        >
            <Input
                autoFocus
                aria-label="Canvas name"
                value={draft}
                maxLength={400}
                disabled={savingName}
                onChange={(event: ChangeEvent<HTMLInputElement>) => setDraft(event.target.value)}
                onBlur={() => !savingName && renameCanvas(draft)}
                onKeyDown={(event: KeyboardEvent<HTMLInputElement>) => {
                    if (event.key === 'Escape') {
                        setRenaming(false)
                    }
                }}
                data-attr="canvas-rename-input"
            />
        </form>
    )
}

/** The canvas's name, its build status, and the actions on the canvas as a whole. */
export function CanvasSceneHeader(): JSX.Element {
    const { canvas, renaming } = useValues(canvasSceneLogic)
    const { setRenaming, copyLink, deleteCanvas } = useActions(canvasSceneLogic)

    return (
        <header className="flex min-h-12 shrink-0 items-center gap-2 border-b border-border px-4 py-2">
            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
                {!canvas ? (
                    <Skeleton className="h-5 w-48" />
                ) : renaming ? (
                    <CanvasNameInput name={canvas.name} />
                ) : (
                    <button
                        type="button"
                        className="min-w-0 max-w-full cursor-text rounded-sm text-left"
                        onClick={() => setRenaming(true)}
                        aria-label={`Rename ${canvas.name}`}
                        data-attr="canvas-name"
                    >
                        <Heading render={<h1 />} size="base" className="truncate">
                            {canvas.name}
                        </Heading>
                    </button>
                )}
                {canvas && !renaming && <CanvasBuildStatusBadge />}
            </div>
            {canvas && (
                <DropdownMenu>
                    <Tooltip>
                        {/* quill's triggers do not forward refs under React 18, so a span anchors the tooltip. */}
                        <TooltipTrigger delay={0} render={<span className="inline-flex" />}>
                            <DropdownMenuTrigger
                                render={
                                    <Button
                                        variant="default"
                                        size="icon-sm"
                                        aria-label="Canvas actions"
                                        data-attr="canvas-actions-menu"
                                    />
                                }
                            >
                                <IconEllipsis />
                            </DropdownMenuTrigger>
                        </TooltipTrigger>
                        <TooltipContent>Canvas actions</TooltipContent>
                    </Tooltip>
                    <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={() => setRenaming(true)} data-attr="canvas-action-rename">
                            <IconPencil />
                            Rename
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={() => copyLink()} data-attr="canvas-action-copy-link">
                            <IconCopy />
                            Copy link
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                            variant="destructive"
                            onClick={() => deleteCanvas()}
                            data-attr="canvas-action-delete"
                        >
                            <IconTrash />
                            Delete
                        </DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            )}
        </header>
    )
}
