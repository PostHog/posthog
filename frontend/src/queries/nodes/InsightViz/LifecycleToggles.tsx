import { LifecycleQuery } from '~/queries/schema'
import { LifecycleToggle } from '~/types'
import { LemonCheckbox, LemonLabel } from '@posthog/lemon-ui'
import { IconDragHandle } from 'lib/lemon-ui/icons'
import { useState, DragEventHandler } from 'react'

export type DragAndDropState = {
    draggedFrom: number | null
    draggedTo: number | null
    isDragging: boolean
}

const lifecycles: { [key: string]: { name: LifecycleToggle; tooltip: string; color: string } } = {
    new: {
        name: 'new',
        tooltip: 'Users who were first seen on this period and did the activity during the period.',
        color: 'var(--lifecycle-new)',
    },
    returning: {
        name: 'returning',
        tooltip: 'Users who did activity both this and previous period.',
        color: 'var(--lifecycle-returning)',
    },
    resurrecting: {
        name: 'resurrecting',
        tooltip:
            'Users who did the activity this period but did not do the activity on the previous period (i.e. were inactive for 1 or more periods).',
        color: 'var(--lifecycle-resurrecting)',
    },
    dormant: {
        name: 'dormant',
        tooltip:
            'Users who went dormant on this period, i.e. users who did not do the activity this period but did the activity on the previous period.',
        color: 'var(--lifecycle-dormant)',
    },
}

type LifecycleTogglesProps = {
    query: LifecycleQuery
    setQuery: (node: LifecycleQuery) => void
}

const DEFAULT_LIFECYCLE_TOGGLES: LifecycleToggle[] = ['new', 'returning', 'dormant', 'resurrecting']

export function LifecycleToggles({ query, setQuery }: LifecycleTogglesProps): JSX.Element {
    const toggledLifecycles = query.lifecycleFilter?.toggledLifecycles || DEFAULT_LIFECYCLE_TOGGLES
    const lifecyclesOrder = query.lifecycleFilter?.lifecyclesOrder || DEFAULT_LIFECYCLE_TOGGLES

    const setToggledLifecycles = (lifecycles: LifecycleToggle[]): void => {
        setQuery({
            ...query,
            lifecycleFilter: {
                ...query.lifecycleFilter,
                toggledLifecycles: lifecycles,
            },
        })
    }

    const setLifecyclesOrder = (lifecycles: LifecycleToggle[]): void => {
        setQuery({
            ...query,
            lifecycleFilter: {
                ...query.lifecycleFilter,
                lifecyclesOrder: lifecycles,
            },
        })
    }

    const toggleLifecycle = (name: LifecycleToggle): void => {
        if (toggledLifecycles.includes(name)) {
            setToggledLifecycles(toggledLifecycles.filter((n) => n !== name))
        } else {
            setToggledLifecycles([...toggledLifecycles, name])
        }
    }

    // basic starting state for holding and handling the drag data
    const [dragAndDrop, setDragAndDrop] = useState<DragAndDropState>({
        draggedFrom: null,
        draggedTo: null,
        isDragging: false,
    })

    const onDragStart: DragEventHandler<HTMLDivElement> = (event): void => {
        const initialPosition = Number(event.currentTarget.dataset.position)

        setDragAndDrop({
            draggedTo: null,
            draggedFrom: initialPosition,
            isDragging: true,
        })
    }

    const onDragOver: DragEventHandler<HTMLDivElement> = (event): void => {
        event.preventDefault()
        dragAndDrop.draggedTo = Number(event.currentTarget.dataset.position)
    }

    const onDrop: DragEventHandler<HTMLDivElement> = (): void => {
        const draggedFrom = dragAndDrop.draggedFrom
        const draggedTo = dragAndDrop.draggedTo

        // valid this is a valid place to move over
        if (draggedFrom == null || draggedTo == null) {
            return
        }

        let copiedList = lifecyclesOrder
        const itemDragged = copiedList[draggedFrom]

        // remove item and re-add it where we want it
        const remainingItems = copiedList.filter((_, index) => index !== draggedFrom)
        copiedList = [...remainingItems.slice(0, draggedTo), itemDragged, ...remainingItems.slice(draggedTo)]

        // updated the query, so the order persists.
        setLifecyclesOrder(copiedList)

        setDragAndDrop({
            draggedFrom: null,
            draggedTo: null,
            isDragging: false,
        })
    }

    return (
        <div className="flex flex-col -mt-1 uppercase">
            {lifecyclesOrder.map((key, i) => (
                <div
                    key={key}
                    data-position={i}
                    draggable="true"
                    onDragStart={onDragStart}
                    onDragOver={onDragOver}
                    onDrop={onDrop}
                >
                    <LemonLabel info={lifecycles[key].tooltip}>
                        <IconDragHandle />
                        <LemonCheckbox
                            label={lifecycles[key].name}
                            color={lifecycles[key].color}
                            checked={toggledLifecycles.includes(lifecycles[key].name)}
                            onChange={() => toggleLifecycle(lifecycles[key].name)}
                        />
                    </LemonLabel>
                </div>
            ))}
        </div>
    )
}
