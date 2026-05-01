import { within } from '@testing-library/react'

// DOM element accessors and cleanup helpers for insight tests. These aren't
// user actions (those live in interactions.ts) — they're getters for asserting
// presence/absence and teardown helpers for roots rendered outside
// @testing-library's tree.

const PERSONS_MODAL_SELECTOR = '[data-attr="persons-modal"]'
// PersonDisplay renders each actor's display name inside a link tagged with
// `data-attr="goto-person-email-<distinct_id>"`. Using this prefix keeps the
// helper off of LemonModal's CSS class names.
const ACTOR_NAME_SELECTOR = '[data-attr^="goto-person-email-"]'

export const personsModal = {
    /** Current persons modal element, or null if none is open. */
    get(): HTMLElement | null {
        return document.querySelector(PERSONS_MODAL_SELECTOR)
    },
    /** Text of the modal heading (e.g. "Results on Wednesday 12 Jun"). */
    title(): string {
        const modal = this.get()
        if (!modal) {
            return ''
        }
        return within(modal).queryByRole('heading')?.textContent ?? ''
    },
    /** Display names of the actor rows currently rendered in the modal.
     *  Empty while the modal is loading; use waitFor to assert. */
    actorNames(): string[] {
        const modal = this.get()
        if (!modal) {
            return []
        }
        return Array.from(modal.querySelectorAll(ACTOR_NAME_SELECTOR))
            .map((el) => el.textContent?.trim() ?? '')
            .filter(Boolean)
    },
    /** Remove any persons modals left over in document.body. Call from an
     *  afterEach — openPersonsModal renders via createRoot into divs it
     *  appends outside testing-library's render tree, so cleanup() won't
     *  touch them. */
    cleanupAll(): void {
        Array.from(document.body.children).forEach((child) => {
            if (child.querySelector(PERSONS_MODAL_SELECTOR)) {
                child.remove()
            }
        })
    },
}
