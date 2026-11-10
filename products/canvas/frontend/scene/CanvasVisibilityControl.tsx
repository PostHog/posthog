import { useActions, useValues } from 'kea'

import { IconChevronDown, IconGlobe, IconLock, IconPeople } from '@posthog/icons'
import {
    Badge,
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { teamLogic } from 'scenes/teamLogic'

import { CanvasVisibility } from '../canvasVisibility'
import { CanvasMakePublicDialog } from './CanvasMakePublicDialog'
import { canvasSceneLogic } from './canvasSceneLogic'

const LABELS: Record<CanvasVisibility, string> = { private: 'Private', public: 'Public', shared: 'Shared' }
const ICONS: Record<CanvasVisibility, JSX.Element> = {
    private: <IconLock />,
    public: <IconGlobe />,
    shared: <IconPeople />,
}

function visibilityHint(
    visibility: CanvasVisibility,
    { project, owner, spaceName }: { project: string; owner: string | null; spaceName: string | null }
): string {
    if (visibility === 'private') {
        return 'Only you can see this canvas.'
    }
    if (visibility === 'shared') {
        return `This canvas is in ${spaceName ? `the older space ${spaceName}` : 'an older space'}. Only its members can see it.`
    }
    return owner
        ? `${owner} made this canvas public. Everyone in ${project} can see it.`
        : `Everyone in ${project} can see this canvas.`
}

/** Who can see the canvas, in the header. Its creator can change it here. Everyone else sees a label. */
export function CanvasVisibilityControl(): JSX.Element | null {
    const { canvas, space, visibility, isCreator, visibilityChanging, makePublicOpen } = useValues(canvasSceneLogic)
    const { openMakePublic, setCanvasVisibility } = useActions(canvasSceneLogic)
    const { currentTeam } = useValues(teamLogic)

    if (!canvas || !visibility || (!isCreator && visibility === 'private')) {
        return null
    }
    const hint = visibilityHint(visibility, {
        project: currentTeam?.name || 'this project',
        owner: isCreator ? null : canvas.created_by.first_name || canvas.created_by.email || 'A teammate',
        spaceName: space?.name ?? null,
    })
    const content = (
        <>
            {ICONS[visibility]}
            <span className="hidden @min-[32rem]/canvas-toolbar:inline">{LABELS[visibility]}</span>
        </>
    )
    // quill's Badge and DropdownMenuTrigger do not forward refs under React 18, so a span anchors the tooltip.
    const withHint = (trigger: JSX.Element): JSX.Element => (
        <Tooltip>
            <TooltipTrigger
                delay={300}
                render={<span tabIndex={isCreator ? undefined : 0} className="inline-flex rounded-sm" />}
            >
                {trigger}
            </TooltipTrigger>
            <TooltipContent className="max-w-72">{hint}</TooltipContent>
        </Tooltip>
    )

    if (!isCreator) {
        return withHint(
            <Badge aria-label={LABELS[visibility]} data-attr="canvas-visibility-readonly">
                {content}
            </Badge>
        )
    }
    return (
        <>
            <DropdownMenu>
                {withHint(
                    <DropdownMenuTrigger
                        render={
                            <Button
                                variant="outline"
                                size="sm"
                                loading={visibilityChanging}
                                aria-label={`${LABELS[visibility]}. Change who can see this canvas`}
                                data-attr="canvas-visibility"
                            />
                        }
                    >
                        {content}
                        <IconChevronDown />
                    </DropdownMenuTrigger>
                )}
                <DropdownMenuContent align="end" className="min-w-48">
                    {visibility !== 'public' && (
                        <DropdownMenuItem onClick={() => openMakePublic()} data-attr="canvas-visibility-make-public">
                            <IconGlobe />
                            Make public…
                        </DropdownMenuItem>
                    )}
                    {visibility !== 'private' && (
                        <DropdownMenuItem
                            onClick={() => setCanvasVisibility('private')}
                            data-attr="canvas-visibility-make-private"
                        >
                            <IconLock />
                            Make private
                        </DropdownMenuItem>
                    )}
                </DropdownMenuContent>
            </DropdownMenu>
            {makePublicOpen && <CanvasMakePublicDialog />}
        </>
    )
}
