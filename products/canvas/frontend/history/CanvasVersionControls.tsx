import { useActions, useValues } from 'kea'

import { IconRedo, IconUndo } from '@posthog/icons'
import { Badge, Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { canvasEditLogic } from '../editing/canvasEditLogic'
import { canvasSceneLogic } from '../scene/canvasSceneLogic'
import { canvasSidePanelLogic } from '../sidePanel/canvasSidePanelLogic'
import { canvasHistoryLogic } from './canvasHistoryLogic'

function StepButton({
    label,
    disabledReason,
    onClick,
    dataAttr,
    children,
}: {
    label: string
    disabledReason: string | null
    onClick: () => void
    dataAttr: string
    children: JSX.Element
}): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger
                delay={0}
                render={
                    <Button
                        size="icon-sm"
                        variant="default"
                        aria-label={label}
                        disabled={!!disabledReason}
                        onClick={onClick}
                        data-attr={dataAttr}
                    />
                }
            >
                {children}
            </TooltipTrigger>
            <TooltipContent>{disabledReason ?? label}</TooltipContent>
        </Tooltip>
    )
}

/** Undo and redo through versions, and buttons that open the timeline tab, in the canvas header. Undo and redo through local edits while editing. */
export function CanvasVersionControls(): JSX.Element | null {
    const { versions, drafts, displayedVersionId, liveBuild, canUndo, canRedo, browsedDraft, isGenerating } =
        useValues(canvasHistoryLogic)
    const { undo, redo } = useActions(canvasHistoryLogic)
    const { canvas } = useValues(canvasSceneLogic)
    const { openTab } = useActions(canvasSidePanelLogic)
    const { sourceEditing, canUndoEdit, canRedoEdit } = useValues(canvasEditLogic)
    const { undoEdit, redoEdit } = useActions(canvasEditLogic)

    // While editing, undo and redo step through local edits instead of published versions, like PostHog Desktop.
    if (sourceEditing) {
        return (
            <div
                role="group"
                aria-label="Edits"
                className="flex items-center gap-0.5"
                data-attr="canvas-version-controls"
            >
                <StepButton
                    label="Undo"
                    disabledReason={canUndoEdit ? null : 'There is nothing to undo.'}
                    onClick={undoEdit}
                    dataAttr="canvas-edit-undo"
                >
                    <IconUndo />
                </StepButton>
                <StepButton
                    label="Redo"
                    disabledReason={canRedoEdit ? null : 'There is nothing to redo.'}
                    onClick={redoEdit}
                    dataAttr="canvas-edit-redo"
                >
                    <IconRedo />
                </StepButton>
            </div>
        )
    }
    if (versions.length === 0 && drafts.length === 0) {
        return null
    }
    const openTimeline = (): void => {
        if (canvas) {
            openTab('timeline', canvas.id)
        }
    }
    const generatingReason = isGenerating ? 'The agent is changing the canvas. Wait for it to finish.' : null

    return (
        <div className="flex min-w-0 items-center gap-1" data-attr="canvas-version-controls">
            <div role="group" aria-label="Versions" className="flex items-center gap-0.5">
                <StepButton
                    label="Previous version"
                    disabledReason={generatingReason ?? (canUndo ? null : 'This is the oldest version.')}
                    onClick={undo}
                    dataAttr="canvas-version-undo"
                >
                    <IconUndo />
                </StepButton>
                <StepButton
                    label="Next version"
                    disabledReason={generatingReason ?? (canRedo ? null : 'This is the latest version.')}
                    onClick={redo}
                    dataAttr="canvas-version-redo"
                >
                    <IconRedo />
                </StepButton>
                {!browsedDraft && versions.length > 0 && (
                    <Tooltip>
                        <TooltipTrigger
                            delay={0}
                            render={
                                <Button
                                    size="sm"
                                    variant="default"
                                    onClick={openTimeline}
                                    data-attr="canvas-version-menu"
                                />
                            }
                        >
                            <span translate="no">{`v${
                                versions.length -
                                Math.max(
                                    0,
                                    versions.findIndex((version) => version.id === displayedVersionId)
                                )
                            }/${versions.length}`}</span>
                            {displayedVersionId === liveBuild?.source_version_id && <span>· Live</span>}
                        </TooltipTrigger>
                        <TooltipContent>Show all versions</TooltipContent>
                    </Tooltip>
                )}
            </div>
            {browsedDraft && <Badge variant="warning">Draft preview</Badge>}
            {drafts.length > 0 && (
                <Button size="sm" variant="default" onClick={openTimeline} data-attr="canvas-drafts-menu">
                    {`Drafts (${drafts.length})`}
                </Button>
            )}
        </div>
    )
}
