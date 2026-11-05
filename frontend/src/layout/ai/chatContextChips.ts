import { type AttachedContextItem, attachedContextItemKey } from '~/layout/ai/attachedContext'

// Bounds the persisted store, because every chat a browser starts adds an entry to localStorage.
const MAX_PERSISTED_CHATS = 50

/** What a composer needs to draw and link one context item. A chip never carries the item's `value` payload. */
export interface ContextChip extends Pick<AttachedContextItem, 'type' | 'key' | 'pageId' | 'dismissible'> {
    id: string
    label: string
    dismissGroup?: string
}

export type ChatChipsByTask = Record<string, ContextChip[]>

function hasKey(item: AttachedContextItem): boolean {
    return item.key !== undefined && item.key !== null && item.key !== ''
}

function keyedLabel(item: AttachedContextItem): string {
    return `${item.type} ${item.key ?? ''}`.trim()
}

function chipReference({
    type,
    key,
    pageId,
    dismissible,
}: AttachedContextItem): Pick<ContextChip, 'type' | 'key' | 'pageId' | 'dismissible'> {
    return { type, key, pageId, dismissible }
}

/** The chip for an item on screen now. Its id matches `attachedContextItemKey`, so it can dismiss the item. */
export function contextChip(item: AttachedContextItem): ContextChip {
    return {
        ...chipReference(item),
        id: attachedContextItemKey(item),
        label: item.label || (item.type === 'text' && item.value) || keyedLabel(item) || 'Text',
        dismissGroup: item.dismissGroup,
    }
}

/**
 * The chip a chat stores. `value` can hold ingested data, such as survey responses, and the agent already has it, so
 * neither the id nor the label of a stored chip may derive from it.
 */
function storedChatChip(item: AttachedContextItem): ContextChip {
    if (hasKey(item)) {
        return { ...chipReference(item), id: attachedContextItemKey(item), label: item.label || keyedLabel(item) }
    }
    const label = item.label || (item.type === 'text' ? 'Text' : item.type)
    return { ...chipReference(item), id: `${item.type}:${label}`, label }
}

function withChatLast(chats: ChatChipsByTask, taskId: string, chips: ContextChip[]): ChatChipsByTask {
    const { [taskId]: _previous, ...others } = chats
    return { ...Object.fromEntries(Object.entries(others).slice(-(MAX_PERSISTED_CHATS - 1))), [taskId]: chips }
}

export function addChatChips(chats: ChatChipsByTask, taskId: string, items: AttachedContextItem[]): ChatChipsByTask {
    const existing = chats[taskId] ?? []
    const seenIds = new Set(existing.map((chip) => chip.id))
    const added: ContextChip[] = []
    for (const item of items) {
        const chip = storedChatChip(item)
        if (!item.hidden && !seenIds.has(chip.id)) {
            seenIds.add(chip.id)
            added.push(chip)
        }
    }
    return added.length > 0 ? withChatLast(chats, taskId, [...existing, ...added]) : chats
}

export function removeChatChip(chats: ChatChipsByTask, taskId: string, chipId: string): ChatChipsByTask {
    const existing = chats[taskId]
    return existing ? { ...chats, [taskId]: existing.filter((chip) => chip.id !== chipId) } : chats
}
