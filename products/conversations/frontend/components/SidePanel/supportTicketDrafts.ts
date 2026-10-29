import { JSONContent } from '@tiptap/core'

// pinned: localStorage key prefix. Renaming it drops every saved draft, and logout clears drafts by it.
export const DRAFT_KEY_PREFIX = 'support-ticket-draft:'
const NEW_TICKET_SLOT = 'new'
const TICKET_SLOT_PREFIX = 'ticket:'

const DRAFT_MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000

export interface TicketDraft {
    content: JSONContent
    updatedAt: number
}

export interface NewTicketDraft {
    content: JSONContent | null
    context: string | null
    updatedAt: number
}

export interface StoredDrafts {
    newTicket: NewTicketDraft | null
    tickets: Record<string, TicketDraft>
}

export const NO_DRAFTS: StoredDrafts = { newTicket: null, tickets: {} }

// One key per user, so a tab left open after a user switch cannot write into the next user's drafts.
// One key per ticket, so two tabs that edit different tickets do not overwrite each other.
function draftKey(ownerId: string, slot: string): string {
    return `${DRAFT_KEY_PREFIX}${ownerId}:${slot}`
}

function writeDraft(key: string, draft: TicketDraft | NewTicketDraft | null): void {
    try {
        if (draft) {
            localStorage.setItem(key, JSON.stringify(draft))
        } else {
            localStorage.removeItem(key)
        }
    } catch {
        // A full or disabled storage loses only the saved copy. The draft in memory stays.
    }
}

export function saveNewTicketDraft(ownerId: string, draft: NewTicketDraft | null): void {
    writeDraft(draftKey(ownerId, NEW_TICKET_SLOT), draft)
}

export function saveTicketDraft(ownerId: string, ticketId: string, draft: TicketDraft | null): void {
    writeDraft(draftKey(ownerId, `${TICKET_SLOT_PREFIX}${ticketId}`), draft)
}

/** Reads one user's drafts and removes the ones older than 30 days. */
export function readDrafts(ownerId: string, now: number): StoredDrafts {
    const drafts: StoredDrafts = { newTicket: null, tickets: {} }
    const ownerPrefix = draftKey(ownerId, '')
    try {
        for (let index = localStorage.length - 1; index >= 0; index--) {
            const key = localStorage.key(index)
            if (!key?.startsWith(ownerPrefix)) {
                continue
            }
            let draft: TicketDraft | NewTicketDraft | null = null
            try {
                draft = JSON.parse(localStorage.getItem(key) ?? 'null')
            } catch {
                draft = null
            }
            if (!draft || typeof draft.updatedAt !== 'number' || now - draft.updatedAt >= DRAFT_MAX_AGE_MS) {
                localStorage.removeItem(key)
                continue
            }
            const slot = key.slice(ownerPrefix.length)
            if (slot === NEW_TICKET_SLOT) {
                drafts.newTicket = draft as NewTicketDraft
            } else if (slot.startsWith(TICKET_SLOT_PREFIX) && draft.content) {
                drafts.tickets[slot.slice(TICKET_SLOT_PREFIX.length)] = draft as TicketDraft
            }
        }
    } catch {
        return NO_DRAFTS
    }
    return drafts
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
