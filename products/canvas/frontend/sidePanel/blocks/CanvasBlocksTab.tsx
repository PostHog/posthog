import { useActions, useValues } from 'kea'
import { PointerEvent } from 'react'

import { IconChevronLeft, IconSparkles } from '@posthog/icons'
import { Button, Skeleton } from '@posthog/quill'

import { canvasEditLogic } from '../../editing/canvasEditLogic'
import { isRootSelection } from '../../editing/canvasSourceSnapshots'
import { LibraryEntry, libraryIcon, libraryLabel } from '../../editing/libraryCatalog'
import { beginSourceDrag } from '../../editing/sourceDrag'
import { CanvasBlocksLibrary } from './CanvasBlocksLibrary'
import { CanvasBlocksNotice } from './CanvasBlocksNotice'
import { CanvasBlocksSaveIndicator } from './CanvasBlocksSaveIndicator'
import { CanvasSourceInspector } from './inspector/CanvasSourceInspector'

/**
 * The Blocks tab of an edited canvas: the library to add blocks from, or the inspector for the
 * selected block, with the save state and any save problem on top. Like PostHog Desktop's Blocks panel.
 */
export function CanvasBlocksTab({ canvasId }: { canvasId: string }): JSX.Element {
    const { entry, selection, libraryOpen, saveStatus } = useValues(canvasEditLogic({ id: canvasId }))
    const {
        setLibraryOpen,
        addAfterSelection,
        dropBlock,
        updateProps,
        setText,
        duplicateSelection,
        removeSelection,
        retrySave,
        resolveConflict,
        askAgent,
    } = useActions(canvasEditLogic({ id: canvasId }))

    if (!entry || !saveStatus) {
        return (
            <div className="flex flex-col gap-2 p-3" aria-label="Loading blocks">
                <Skeleton className="h-8 w-full" />
                <Skeleton className="h-12 w-full" />
                <Skeleton className="h-12 w-full" />
            </div>
        )
    }
    const isRoot = isRootSelection(entry, selection)
    const SelectedIcon = libraryIcon(selection?.blockType ?? null)
    const inspecting = !!selection && !libraryOpen
    const addsAfter = selection && !isRoot ? libraryLabel(selection.blockType, selection.tag) : null

    const addFromLibrary = (blockType: string): void => {
        setLibraryOpen(true)
        addAfterSelection(blockType)
    }
    const onLibraryPointerDown = (event: PointerEvent, item: LibraryEntry): void => {
        if (event.button !== 0) {
            return
        }
        event.preventDefault()
        beginSourceDrag({
            source: { kind: 'new', blockType: item.type },
            startX: event.clientX,
            startY: event.clientY,
            onDrop: (source, hit) => {
                setLibraryOpen(true)
                dropBlock(source, hit)
            },
            onClick: () => addFromLibrary(item.type),
        })
    }

    return (
        <div className="flex h-full min-h-0 flex-col" data-attr="canvas-blocks-tab">
            <div className="flex h-9 shrink-0 items-center gap-1.5 border-b border-border px-3">
                {inspecting ? (
                    <Button
                        variant="default"
                        size="xs"
                        onClick={() => setLibraryOpen(true)}
                        data-attr="canvas-blocks-all"
                    >
                        <IconChevronLeft />
                        All blocks
                    </Button>
                ) : (
                    <span className="text-xs font-medium text-muted-foreground">Library</span>
                )}
                <div className="flex-1" />
                <CanvasBlocksSaveIndicator status={saveStatus} />
            </div>
            {entry.saveError ? (
                <CanvasBlocksNotice tone="error" title="Your changes are not saved" detail={entry.saveError}>
                    <Button variant="outline" size="xs" onClick={() => retrySave()} data-attr="canvas-save-retry">
                        Try again
                    </Button>
                    <Button
                        variant="default"
                        size="xs"
                        onClick={() =>
                            askAgent(
                                `Saving this canvas fails with: "${entry.saveError}". Fix the canvas source so it passes validation.`
                            )
                        }
                        data-attr="canvas-save-ask-agent"
                    >
                        <IconSparkles />
                        Ask the agent to fix
                    </Button>
                </CanvasBlocksNotice>
            ) : null}
            {entry.conflict ? (
                <CanvasBlocksNotice
                    tone="warning"
                    title="This canvas changed somewhere else"
                    detail="A newer version was saved while you edited. Load it and drop your unsaved edits, or keep your edits and replace it."
                >
                    <Button
                        variant="outline"
                        size="xs"
                        onClick={() => resolveConflict(false)}
                        data-attr="canvas-conflict-load-latest"
                    >
                        Load the latest
                    </Button>
                    <Button
                        variant="default"
                        size="xs"
                        onClick={() => resolveConflict(true)}
                        data-attr="canvas-conflict-keep-mine"
                    >
                        Keep my edits
                    </Button>
                </CanvasBlocksNotice>
            ) : null}
            {inspecting && selection ? (
                <div className="min-h-0 flex-1 overflow-y-auto">
                    <div className="flex items-center gap-2.5 border-b border-border px-3 py-2.5">
                        <div className="flex size-7 shrink-0 items-center justify-center rounded-md bg-fill-hover text-foreground">
                            <SelectedIcon className="size-4" />
                        </div>
                        <div className="min-w-0">
                            <div className="text-xs font-medium text-foreground">
                                {isRoot ? 'Canvas' : libraryLabel(selection.blockType, selection.tag)}
                            </div>
                            <div className="truncate font-mono text-xs text-muted-foreground" translate="no">
                                {selection.source?.file ?? ''}
                            </div>
                        </div>
                    </div>
                    <CanvasSourceInspector
                        key={selection.blockId ?? `${selection.source?.file}:${selection.source?.start}`}
                        selection={selection}
                        isRoot={isRoot}
                        onProps={(props) => updateProps(selection, props)}
                        onText={(text) => setText(selection, text)}
                        onDuplicate={() => duplicateSelection(selection)}
                        onRemove={() => removeSelection(selection)}
                    />
                    {isRoot ? null : (
                        <div className="px-3 pb-3">
                            <Button
                                variant="outline"
                                size="sm"
                                onClick={() =>
                                    askAgent(
                                        `Change the ${libraryLabel(selection.blockType, selection.tag).toLowerCase()} at ${selection.source?.file ?? 'the canvas'}${selection.blockId ? ` (blockId ${selection.blockId})` : ''}: `
                                    )
                                }
                                data-attr="canvas-block-ask-agent"
                            >
                                <IconSparkles />
                                Ask the agent about this
                            </Button>
                        </div>
                    )}
                </div>
            ) : (
                <CanvasBlocksLibrary
                    addsAfter={addsAfter}
                    onPointerDown={onLibraryPointerDown}
                    onActivate={(item) => addFromLibrary(item.type)}
                    onAskAgent={askAgent}
                />
            )}
        </div>
    )
}
