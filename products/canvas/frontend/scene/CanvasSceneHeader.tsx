import { useActions, useValues } from 'kea'

import { IconCopy, IconEllipsis, IconPalette, IconTrash } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { CanvasVersionControls } from '../history/CanvasVersionControls'
import { CanvasBuildStatus } from './CanvasBuildStatus'
import { CanvasGenerationIndicator } from './CanvasGenerationIndicator'
import { CanvasRuntimeErrorNotice } from './CanvasRuntimeErrorNotice'
import { canvasSceneLogic } from './canvasSceneLogic'
import { CanvasSidePanelToggle } from './CanvasSidePanelToggle'

/** The canvas's name, its build status, and the actions on the canvas as a whole. Select the name to rename it. */
export function CanvasSceneHeader(): JSX.Element {
    const { canvas } = useValues(canvasSceneLogic)
    const { renameCanvas, copyLink, deleteCanvas } = useActions(canvasSceneLogic)

    return (
        <SceneTitleSection
            name={canvas?.name ?? null}
            isLoading={!canvas}
            resourceType={{ type: 'canvas', forceIcon: <IconPalette /> }}
            canEdit={!!canvas}
            onNameChange={renameCanvas}
            saveOnBlur
            renameDebounceMs={0}
            actions={
                canvas ? (
                    <div data-quill className="flex flex-wrap items-center justify-end gap-2">
                        {/* Status first, then history, then the panel and canvas menus. Each group wraps as one. */}
                        <div className="flex flex-wrap items-center gap-1 empty:hidden">
                            <CanvasGenerationIndicator />
                            <CanvasBuildStatus />
                            <CanvasRuntimeErrorNotice />
                        </div>
                        <CanvasVersionControls />
                        <div className="flex items-center gap-1">
                            <CanvasSidePanelToggle />
                            <DropdownMenu>
                                <Tooltip>
                                    {/* quill's triggers do not forward refs under React 18, so a span anchors the tooltip. */}
                                    <TooltipTrigger delay={0} render={<span className="inline-flex" />}>
                                        <DropdownMenuTrigger
                                            render={
                                                <Button
                                                    variant="outline"
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
                        </div>
                    </div>
                ) : undefined
            }
        />
    )
}
