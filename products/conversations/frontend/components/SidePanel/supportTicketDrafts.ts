import { JSONContent } from '@tiptap/core'

// pinned: localStorage keys. Renaming them drops every draft people have saved.
const DRAFT_KEY_PREFIX = 'support-ticket-draft:'
export const NEW_TICKET_DRAFT_STORAGE_KEY = `${DRAFT_KEY_PREFIX}new`
export const NEW_TICKET_CONTEXT_STORAGE_KEY = `${DRAFT_KEY_PREFIX}new-context`
export const TICKET_DRAFTS_STORAGE_KEY = `${DRAFT_KEY_PREFIX}tickets`
export const DRAFTS_OWNER_STORAGE_KEY = `${DRAFT_KEY_PREFIX}owner`
export const NEW_TICKET_DRAFT_UPDATED_AT_STORAGE_KEY = `${DRAFT_KEY_PREFIX}new-updated-at`

const DRAFT_MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000

export interface TicketDraft {
    content: JSONContent
    updatedAt: number
}

/** Firing the same CTA twice must not add its prefill twice. */
export function appendDraft(existing: JSONContent | null, addition: JSONContent): JSONContent {
    const existingNodes = existing?.content ?? []
    const additionNodes = addition.content ?? []
    if (existingNodes.length === 0) {
        return addition
    }
    const tail = existingNodes.slice(-additionNodes.length)
    if (additionNodes.length > 0 && JSON.stringify(tail) === JSON.stringify(additionNodes)) {
        return existing as JSONContent
    }
    return { ...existing, content: [...existingNodes, ...additionNodes] }
}

export function isDraftStale(updatedAt: number, now: number): boolean {
    return now - updatedAt >= DRAFT_MAX_AGE_MS
}

export function pruneStaleTicketDrafts(drafts: Record<string, TicketDraft>, now: number): Record<string, TicketDraft> {
    return Object.fromEntries(Object.entries(drafts).filter(([, draft]) => !isDraftStale(draft.updatedAt, now)))
}

/** Drafts can hold anything a person typed to support, so logout removes them from a shared browser. */
export function clearSupportTicketDrafts(): void {
    try {
        for (let index = localStorage.length - 1; index >= 0; index--) {
            const key = localStorage.key(index)
            if (key?.startsWith(DRAFT_KEY_PREFIX)) {
                localStorage.removeItem(key)
            }
        }
    } catch {
        // Disabled storage must not prevent logout.
    }
}
