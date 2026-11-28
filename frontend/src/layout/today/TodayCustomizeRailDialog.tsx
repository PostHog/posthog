import { DndContext, PointerSensor, closestCenter, useSensor, useSensors } from '@dnd-kit/core'
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { useActions, useValues } from 'kea'

import {
    Button,
    Callout,
    CalloutClose,
    CalloutContent,
    CalloutDescription,
    CalloutTitle,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@posthog/quill'

import { TodayCustomizeRailRow } from './TodayCustomizeRailRow'
import { todayDesignChangelogLogic } from './todayDesignChangelogLogic'
import { TODAY_RAIL_FOOT_PANE, TODAY_RAIL_LOCKED_PANE } from './todayRailLayout'
import { todayRailLayoutLogic } from './todayRailLayoutLogic'
import { TodayRailPaneCheckbox } from './TodayRailPaneCheckbox'
import type { TodayRailPane } from './todayShellLogic'

/** A pane that keeps its place on the rail: shown, checked and fixed. */
function LockedRow({ pane, reason }: { pane: TodayRailPane; reason: string }): JSX.Element {
    return (
        <div className="flex items-center ps-7">
            <TodayRailPaneCheckbox pane={pane} lockedReason={reason} />
        </div>
    )
}

export function TodayCustomizeRailDialog(): JSX.Element {
    const { arrangedPanes, railHidden, railPanes, customizeOpen, layoutCustomized } = useValues(todayRailLayoutLogic)
    const { customizeHint } = useValues(todayDesignChangelogLogic)
    const { setCustomizeHint } = useActions(todayDesignChangelogLogic)
    const { moveRailPane, toggleRailPane, resetRailLayout, setCustomizeOpen } = useActions(todayRailLayoutLogic)
    const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }))

    return (
        <Dialog open={customizeOpen} onOpenChange={setCustomizeOpen}>
            {/* No dimmed backdrop: the rail beside the dialog changes as the person edits it, so it stays in plain view. */}
            <DialogContent overlayClassName="bg-transparent">
                <DialogHeader>
                    <DialogTitle>Customize navigation</DialogTitle>
                    <DialogDescription>
                        Choose the areas to show on the rail, and drag to reorder them. Areas you hide, and areas that
                        don't fit a short window, move to More.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    {/* The last step of the design changelog's demo, which ends in this dialog. */}
                    {customizeHint && (
                        <Callout tone="info" className="mb-3">
                            <CalloutContent>
                                <CalloutTitle>Edit your navigation your way here</CalloutTitle>
                                <CalloutDescription>Show, hide and reorder the areas on the rail.</CalloutDescription>
                            </CalloutContent>
                            <CalloutClose aria-label="Dismiss navigation tip" onClick={() => setCustomizeHint(false)} />
                        </Callout>
                    )}
                    {railPanes.includes(TODAY_RAIL_LOCKED_PANE) && (
                        <LockedRow pane={TODAY_RAIL_LOCKED_PANE} reason="Home is always first on the rail" />
                    )}
                    <DndContext
                        sensors={sensors}
                        collisionDetection={closestCenter}
                        modifiers={[restrictToVerticalAxis, restrictToParentElement]}
                        onDragEnd={({ active, over }) => {
                            const toIndex = arrangedPanes.indexOf(over?.id as TodayRailPane)
                            if (over && active.id !== over.id && toIndex >= 0) {
                                moveRailPane(active.id as TodayRailPane, toIndex)
                            }
                        }}
                    >
                        <SortableContext items={arrangedPanes} strategy={verticalListSortingStrategy}>
                            <div className="flex flex-col">
                                {arrangedPanes.map((pane: TodayRailPane, index: number) => (
                                    <TodayCustomizeRailRow
                                        key={pane}
                                        pane={pane}
                                        shown={!railHidden.includes(pane)}
                                        isFirst={index === 0}
                                        isLast={index === arrangedPanes.length - 1}
                                        onToggle={() => toggleRailPane(pane)}
                                        onMoveUp={() => moveRailPane(pane, index - 1)}
                                        onMoveDown={() => moveRailPane(pane, index + 1)}
                                    />
                                ))}
                            </div>
                        </SortableContext>
                    </DndContext>
                    {railPanes.includes(TODAY_RAIL_FOOT_PANE) && (
                        <LockedRow pane={TODAY_RAIL_FOOT_PANE} reason="Products stays at the bottom of the rail" />
                    )}
                </DialogBody>
                <DialogFooter>
                    {layoutCustomized && (
                        <Button variant="outline" className="me-auto" onClick={resetRailLayout}>
                            Reset to default
                        </Button>
                    )}
                    <Button variant="primary" onClick={() => setCustomizeOpen(false)}>
                        Done
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
