import type { SessionListItemApi } from '../../generated/api.schemas'

export interface SessionNeighbours {
    previous: SessionListItemApi | null
    next: SessionListItemApi | null
}

/** The sessions on either side of the open one in the rows on screen, or null when the rows do not show it. */
export function sessionNeighbours(items: SessionListItemApi[], openSessionId: string | null): SessionNeighbours | null {
    const index = items.findIndex((item) => item.id === openSessionId)
    if (index < 0) {
        return null
    }
    return { previous: items[index - 1] ?? null, next: items[index + 1] ?? null }
}
