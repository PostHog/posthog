import { DndContext, DragEndEvent, MouseSensor, TouchSensor, pointerWithin, useSensor, useSensors } from '@dnd-kit/core'
import { useActions } from 'kea'
import { PropsWithChildren, useCallback } from 'react'

import { DndDescriptor, type DndRequest, dndLogic } from 'lib/dndLogic'

export function GlobalDndContext({ children }: PropsWithChildren): JSX.Element {
    const mouseSensor = useSensor(MouseSensor, {
        // Require the mouse to move by 10 pixels before activating
        activationConstraint: {
            distance: 10,
        },
    })
    const touchSensor = useSensor(TouchSensor, {
        // Press delay of 250ms, with tolerance of 5px of movement
        activationConstraint: {
            delay: 250,
            tolerance: 5,
        },
    })
    const sensors = useSensors(mouseSensor, touchSensor)
    const { handleDrop } = useActions(dndLogic)

    const onDragEnd = useCallback(
        (dragEvent: DragEndEvent) => {
            const sourceDescriptor = dragEvent.active?.data?.current?.dnd as DndDescriptor | undefined
            const targetDescriptor = dragEvent.over?.data?.current?.dnd as DndDescriptor | undefined
            const customRequestBuilder = dragEvent.active?.data?.current?.onDropRequest as
                | ((
                      dragEvent: DragEndEvent,
                      descriptors: { source?: DndDescriptor; target?: DndDescriptor | undefined }
                  ) => DndRequest | null | void)
                | undefined

            if (customRequestBuilder) {
                const builtRequest = customRequestBuilder(dragEvent, {
                    source: sourceDescriptor,
                    target: targetDescriptor,
                })

                if (builtRequest) {
                    handleDrop(builtRequest)
                }
                return
            }

            if (sourceDescriptor) {
                handleDrop({
                    source: sourceDescriptor,
                    target: targetDescriptor,
                    nativeEvent: dragEvent.activatorEvent instanceof DragEvent ? dragEvent.activatorEvent : null,
                })
            }
        },
        [handleDrop]
    )

    return (
        <DndContext sensors={sensors} collisionDetection={pointerWithin} onDragEnd={onDragEnd}>
            {children}
        </DndContext>
    )
}
