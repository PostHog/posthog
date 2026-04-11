const PERSONS_MODAL_SELECTOR = '[data-attr="persons-modal"]'

export const personsModal = {
    /** Current persons modal element, or null if none is open. */
    get(): HTMLElement | null {
        return document.querySelector(PERSONS_MODAL_SELECTOR)
    },
    /** Text of the modal heading (e.g. "Results on Wednesday 12 Jun"). */
    title(): string {
        return this.get()?.querySelector('h3')?.textContent ?? ''
    },
    /** Display names of the actor rows currently rendered in the modal.
     *  Empty while the modal is loading; use waitFor to assert. */
    actorNames(): string[] {
        const modal = this.get()
        if (!modal) {
            return []
        }
        // Each ActorRow wraps the display name in a .font-bold div; the distinct
        // id below it is in a separate sibling so we only grab the name.
        return Array.from(modal.querySelectorAll('[data-attr^="persons-modal-expand-"]'))
            .map((expand) => {
                const row = expand.closest('.rounded')
                return row?.querySelector('.font-bold')?.textContent?.trim() ?? ''
            })
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
