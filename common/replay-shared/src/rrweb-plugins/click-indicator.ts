import type { Replayer } from 'posthog-js/rrweb'

// rrweb re-adds an `active` class the cursor already carries, and the repaint that would restart
// the CSS flash is missing from the shipped bundle, so only the first click of a session flashes.
// Clearing the class after each flash makes rrweb's next add a real change.
export function resetClickIndicatorAfterFlash(replayer: Replayer): () => void {
    const cursor = replayer.wrapper.querySelector('.replayer-mouse')
    if (!cursor) {
        return () => {}
    }

    const clearActive = (): void => cursor.classList.remove('active')

    cursor.addEventListener('animationend', clearActive)
    // A cancelled animation never fires animationend, which would leave the class stuck.
    cursor.addEventListener('animationcancel', clearActive)

    return () => {
        cursor.removeEventListener('animationend', clearActive)
        cursor.removeEventListener('animationcancel', clearActive)
    }
}
