// Waits this long after the last keystroke before the page gets the form, so typing doesn't flood the port.
const FORM_SYNC_DEBOUNCE_MS = 150

/**
 * Keeps the panel's copy of a form that the page owns. The panel sends edits after a pause in typing, and takes the
 * page's copy only when the page changed the form itself, for example when the user picks an element on the page.
 */
export class PageFormSync {
    private adopted: { selectedId: number | 'new' | null; revision: number } | null = null
    private timeout: ReturnType<typeof setTimeout> | null = null

    constructor(private readonly sendForm: () => void) {}

    /** True once for each form the page reports, which the panel then resets its copy to. */
    adopt(selectedId: number | 'new' | null, revision: number): boolean {
        if (this.adopted?.selectedId === selectedId && this.adopted.revision === revision) {
            return false
        }
        this.adopted = { selectedId, revision }
        // A pending edit belongs to the form the page just replaced.
        this.cancel()
        return true
    }

    schedule(): void {
        this.cancel()
        this.timeout = setTimeout(() => {
            this.timeout = null
            this.sendForm()
        }, FORM_SYNC_DEBOUNCE_MS)
    }

    /**
     * Sends a pending edit now. Call it before a command that makes the page change the form, so the page has every
     * edit. With no pending edit the page already has the panel's form, and sending it again could overwrite a change
     * the page made that the panel has not adopted yet.
     */
    flush(): void {
        if (this.timeout === null) {
            return
        }
        this.cancel()
        this.sendForm()
    }

    cancel(): void {
        if (this.timeout !== null) {
            clearTimeout(this.timeout)
            this.timeout = null
        }
    }
}
