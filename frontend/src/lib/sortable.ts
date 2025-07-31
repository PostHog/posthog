// Adapted from https://github.com/clauderic/dnd-kit/pull/805 to fix an issue where variable
// height items in a sortable container were not always firing collisions correctly.
// Should be possible to remove this custom collision detection algorithm once a proper fix
// is merged into dnd-kit.
import { CollisionDetection, DroppableContainer, UniqueIdentifier } from '@dnd-kit/core'

export const verticalSortableListCollisionDetection: CollisionDetection = (args) => {
    if (args.collisionRect.top < (args.active.rect.current?.initial?.top ?? 0)) {
        return highestDroppableContainerMajorityCovered(args)
    }
    return lowestDroppableContainerMajorityCovered(args)
}

// Look for the first (/ furthest up / highest) droppable container that is at least
// 50% covered by the top edge of the dragging container.
const highestDroppableContainerMajorityCovered: CollisionDetection = ({ droppableContainers, collisionRect }) => {
    const ascendingDroppabaleContainers = droppableContainers.sort(sortByRectTop)

    for (const droppableContainer of ascendingDroppabaleContainers) {
        const {
            rect: { current: droppableRect },
        } = droppableContainer

        if (droppableRect) {
            const coveredPercentage =
                (droppableRect.top + droppableRect.height - collisionRect.top) / droppableRect.height

            if (coveredPercentage > 0.5) {
                return [collision(droppableContainer)]
            }
        }
    }

    // if we haven't found anything then we are off the top, so return the first item
    return [collision(ascendingDroppabaleContainers[0])]
}

// Look for the last (/ furthest down / lowest) droppable container that is at least
// 50% covered by the bottom edge of the dragging container.
const lowestDroppableContainerMajorityCovered: CollisionDetection = ({ droppableContainers, collisionRect }) => {
    const descendingDroppabaleContainers = droppableContainers.sort(sortByRectTop).reverse()

    for (const droppableContainer of descendingDroppabaleContainers) {
        const {
            rect: { current: droppableRect },
        } = droppableContainer

        if (droppableRect) {
            const coveredPercentage = (collisionRect.bottom - droppableRect.top) / droppableRect.height

            if (coveredPercentage > 0.5) {
                return [collision(droppableContainer)]
            }
        }
    }

    // if we haven't found anything then we are off the bottom, so return the last item
    return [collision(descendingDroppabaleContainers[0])]
}

const sortByRectTop = (a: DroppableContainer, b: DroppableContainer): number =>
    (a?.rect.current?.top || 0) - (b?.rect.current?.top || 0)

const collision = (dropppableContainer?: DroppableContainer): { id: UniqueIdentifier; value?: DroppableContainer } => {
    return {
        id: dropppableContainer?.id ?? '',
        value: dropppableContainer,
    }
}
