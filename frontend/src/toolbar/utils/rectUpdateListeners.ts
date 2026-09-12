import type { DisposablesManager } from '~/kea-disposables'

/**
 * Listen for scroll and resize, and run `onFrame` on the next animation frame.
 *
 * The toolbar runs on pages we do not control, so a scroll or resize can fire while a Redux
 * reducer is still running. Reading kea `values` or dispatching an action from that stack makes
 * Redux throw, and the throw escapes into the customer page unhandled. The frame hop moves the
 * work off that stack. It also coalesces bursts of events into one update per frame.
 *
 * The listeners stay registered while the tab is hidden, because the browser does not run
 * animation frames there. No work happens until the tab is visible again.
 */
export function addRectUpdateListeners(
    disposables: DisposablesManager,
    onFrame: () => void,
    key = 'rectUpdateListeners'
): void {
    disposables.add(
        () => {
            let frame: number | null = null
            const schedule = (): void => {
                if (frame !== null) {
                    return
                }
                frame = requestAnimationFrame(() => {
                    frame = null
                    onFrame()
                })
            }
            document.addEventListener('scroll', schedule, { capture: true, passive: true })
            window.addEventListener('resize', schedule)
            return () => {
                if (frame !== null) {
                    cancelAnimationFrame(frame)
                    frame = null
                }
                document.removeEventListener('scroll', schedule, { capture: true })
                window.removeEventListener('resize', schedule)
            }
        },
        key,
        { pauseOnPageHidden: false }
    )
}
