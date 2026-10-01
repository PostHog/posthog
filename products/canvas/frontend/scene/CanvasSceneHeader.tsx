import { useActions, useValues } from 'kea'

import { IconCopy, IconEllipsis, IconTrash } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Skeleton,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { canvasSpaceLabel } from '../canvasTasksApi'
import { CanvasVersionControls } from '../history/CanvasVersionControls'
import { CanvasBuildStatus } from './CanvasBuildStatus'
import { CanvasGenerationIndicator } from './CanvasGenerationIndicator'
import { CanvasNameField } from './CanvasNameField'
import { CanvasRuntimeErrorNotice } from './CanvasRuntimeErrorNotice'
import { canvasSceneLogic } from './canvasSceneLogic'
import { CanvasSidePanelToggle } from './CanvasSidePanelToggle'

/**
 * The bar across the top of the canvas, laid out like PostHog Desktop's: the name and version history
 * at the start, then the canvas's status, the side panel, and the canvas menu at the end.
 */
export function CanvasSceneHeader(): JSX.Element {
    const { canvas, space } = useValues(canvasSceneLogic)
    const { copyLink, deleteCanvas } = useActions(canvasSceneLogic)

    return (
        <div
            className="@container/canvas-toolbar flex h-12.5 shrink-0 items-center gap-2 border-b border-border bg-chrome pr-2 pl-1"
            data-attr="canvas-toolbar"
        >
            {canvas ? (
                <>
                    <div className="flex min-w-0 flex-1 items-center gap-1 overflow-hidden">
                        {space && (
                            <>
                                <Button
                                    size="sm"
                                    variant="link-muted"
                                    className="hidden shrink-0 @min-[32rem]/canvas-toolbar:inline-flex"
                                    render={<LinkPrimitive to={urls.taskSpace(space.id)} />}
                                    data-attr="canvas-toolbar-space"
                                >
                                    {canvasSpaceLabel(space)}
                                </Button>
                                <Text
                                    size="sm"
                                    variant="muted"
                                    aria-hidden
                                    className="hidden @min-[32rem]/canvas-toolbar:inline"
                                >
                                    /
                                </Text>
                            </>
                        )}
                        <CanvasNameField />
                        {/* A narrow canvas keeps its name; the timeline tab still reaches every version. */}
                        <div className="hidden @min-[30rem]/canvas-toolbar:contents">
                            <CanvasVersionControls />
                        </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                        <CanvasGenerationIndicator />
                        <CanvasBuildStatus />
                        <CanvasRuntimeErrorNotice />
                        <CanvasSidePanelToggle />
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
                </>
            ) : (
                <Skeleton className="ml-2 h-4 w-40" />
            )}
        </div>
    )
}
