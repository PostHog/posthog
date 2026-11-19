import { DndContext, DragEndEvent } from '@dnd-kit/core'
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonCard, LemonMenu } from '@posthog/lemon-ui'

import { TicketSidebarWidgetEditorRow } from '../TicketSidebarWidgetEditorRow/TicketSidebarWidgetEditorRow'
import {
    TicketSidebarWidgetKey,
    TicketSidebarWidgetSlots,
    ticketSidebarWidget,
} from '../TicketSidebarWidgets/ticketSidebarLayout'
import { ticketSidebarWidgetsLogic } from '../TicketSidebarWidgets/ticketSidebarWidgetsLogic'

export function TicketSidebarWidgetsEditor({ slots }: { slots: TicketSidebarWidgetSlots }): JSX.Element {
    const { layout, draftMatchesDefault } = useValues(ticketSidebarWidgetsLogic)
    const { moveWidget, hideWidget, showWidget, cancelEditing, saveLayout, resetDraftToDefault } =
        useActions(ticketSidebarWidgetsLogic)

    // A widget this user can't see, such as staff actions, keeps its place in the layout but is left out here.
    const canSee = (key: TicketSidebarWidgetKey): boolean => key in slots
    const visible = layout.visible.filter(canSee)
    const addable = layout.hidden.filter(canSee)

    const onDragEnd = ({ active, over }: DragEndEvent): void => {
        if (!over || active.id === over.id) {
            return
        }
        const fromIndex = layout.visible.indexOf(active.id as TicketSidebarWidgetKey)
        const toIndex = layout.visible.indexOf(over.id as TicketSidebarWidgetKey)
        if (fromIndex >= 0 && toIndex >= 0) {
            moveWidget(fromIndex, toIndex)
        }
    }

    return (
        <LemonCard hoverEffect={false} className="p-3 flex flex-col gap-3">
            <div>
                <h3 className="text-sm font-semibold m-0">Edit widgets</h3>
                <p className="text-xs text-secondary m-0 mt-1">
                    Drag widgets to reorder them. A hidden widget doesn't show on any ticket.
                </p>
            </div>

            {visible.length === 0 ? (
                <div className="text-xs text-secondary">All widgets are hidden. Add one to show it on tickets.</div>
            ) : (
                <DndContext onDragEnd={onDragEnd} modifiers={[restrictToVerticalAxis, restrictToParentElement]}>
                    <SortableContext items={visible} strategy={verticalListSortingStrategy}>
                        <div className="flex flex-col gap-2">
                            {visible.map((key) => (
                                <TicketSidebarWidgetEditorRow
                                    key={key}
                                    widgetKey={key}
                                    unavailableReason={slots[key]?.content ? undefined : slots[key]?.unavailableReason}
                                    onHide={() => hideWidget(key)}
                                />
                            ))}
                        </div>
                    </SortableContext>
                </DndContext>
            )}

            <LemonMenu
                placement="bottom-start"
                items={addable.map((key) => ({
                    label: ticketSidebarWidget(key).title,
                    onClick: () => showWidget(key),
                }))}
            >
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconPlus />}
                    disabledReason={addable.length === 0 ? 'All widgets are already shown' : undefined}
                    data-attr="ticket-sidebar-widgets-add"
                >
                    Add widget
                </LemonButton>
            </LemonMenu>

            <div className="flex flex-wrap items-center justify-between gap-2 pt-3 border-t">
                <LemonButton
                    type="tertiary"
                    size="small"
                    onClick={resetDraftToDefault}
                    disabledReason={draftMatchesDefault ? 'This is already the default layout' : undefined}
                    data-attr="ticket-sidebar-widgets-reset"
                >
                    Reset to default
                </LemonButton>
                <div className="flex flex-wrap items-center gap-2">
                    <LemonButton type="secondary" size="small" onClick={cancelEditing}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={saveLayout}
                        data-attr="ticket-sidebar-widgets-save"
                    >
                        Save
                    </LemonButton>
                </div>
            </div>
        </LemonCard>
    )
}
