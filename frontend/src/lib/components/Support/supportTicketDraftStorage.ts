// pinned: localStorage key prefix. Renaming it drops every saved draft, and logout clears drafts by it.
export const DRAFT_KEY_PREFIX = 'support-ticket-draft:'

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
