import { useActions, useValues } from 'kea'

import { IconCopy, IconEllipsis, IconLock, IconTrash } from '@posthog/icons'
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

import { AccessControlObjectModal } from '~/layout/navigation-3000/sidepanel/panels/access_control/AccessControlObjectModal'
import { AccessControlResourceType } from '~/types'

import { canvasSpaceLabel } from '../canvasTasksApi'
import { CanvasEditSaveStatus } from '../editing/CanvasEditSaveStatus'
import { CanvasEditToggle } from '../editing/CanvasEditToggle'
import { CanvasVersionControls } from '../history/CanvasVersionControls'
import { CanvasCommentsMenu } from '../sidePanel/comments/CanvasCommentsMenu'
import { CanvasBuildStatus } from './CanvasBuildStatus'
import { CanvasFullscreenToggle } from './CanvasFullscreenToggle'
import { CanvasGenerationIndicator } from './CanvasGenerationIndicator'
import { CanvasNameField } from './CanvasNameField'
import { CanvasRuntimeErrorNotice } from './CanvasRuntimeErrorNotice'
import { canvasSceneLogic } from './canvasSceneLogic'
import { CanvasSidePanelToggle } from './CanvasSidePanelToggle'
import { CanvasToolbar } from './CanvasToolbar'
import { CanvasVisibilityControl } from './CanvasVisibilityControl'

/**
 * The bar across the top of the canvas, laid out like PostHog Desktop's: the name and version history
 * at the start, then the canvas's status, editing, the side panel, and the canvas menu at the end.
 */
export function CanvasSceneHeader(): JSX.Element {
    const { canvas, space, canManageAccess, accessControlOpen } = useValues(canvasSceneLogic)
    const { copyLink, deleteCanvas, openAccessControl, closeAccessControl } = useActions(canvasSceneLogic)

    if (!canvas) {
        return (
            <CanvasToolbar dataAttr="canvas-toolbar">
                <Skeleton className="ml-2 h-4 w-40" />
            </CanvasToolbar>
        )
    }
    return (
        <CanvasToolbar
            dataAttr="canvas-toolbar"
            actions={
                <>
                    <CanvasGenerationIndicator />
                    <CanvasBuildStatus />
                    <CanvasRuntimeErrorNotice />
                    <CanvasEditSaveStatus />
                    <CanvasEditToggle />
                    <CanvasCommentsMenu />
                    <CanvasFullscreenToggle />
                    <CanvasSidePanelToggle />
                    <CanvasVisibilityControl />
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
                            {canManageAccess && (
                                <DropdownMenuItem
                                    onClick={() => openAccessControl()}
                                    data-attr="canvas-action-manage-access"
                                >
                                    <IconLock />
                                    Manage access
                                </DropdownMenuItem>
                            )}
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
                    {canManageAccess && (
                        <AccessControlObjectModal
                            isOpen={accessControlOpen}
                            onClose={closeAccessControl}
                            resource={AccessControlResourceType.Canvas}
                            resource_id={canvas.id}
                            title="Manage access"
                            description="Everyone who can see this canvas can edit it by default. Make it view-only, or give members and roles their own access."
                        />
                    )}
                </>
            }
        >
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
                    <Text size="sm" variant="muted" aria-hidden className="hidden @min-[32rem]/canvas-toolbar:inline">
                        /
                    </Text>
                </>
            )}
            <CanvasNameField />
            {/* A narrow canvas keeps its name; the timeline tab still reaches every version. */}
            <div className="hidden @min-[30rem]/canvas-toolbar:contents">
                <CanvasVersionControls />
            </div>
        </CanvasToolbar>
    )
}
