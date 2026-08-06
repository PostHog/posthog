/** Id on the setup-command card so inert clicks elsewhere in the takeover can point back to it. */
export const SETUP_COMMAND_CARD_ID = 'self-driving-setup-command'

/**
 * Draw the eye to the one real action on the takeover: scroll the setup command into view and flash
 * it. This is the in-place response to clicks on the example cards and the locked tabs, so a click
 * lands on something visible next to the thing that was clicked instead of only a corner toast.
 */
export function focusSetupCommand(): void {
    const el = document.getElementById(SETUP_COMMAND_CARD_ID)
    if (!el) {
        return
    }
    // Optional-call guards: jsdom (tests) implements neither scrollIntoView nor animate.
    el.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
    // Web Animations API rather than a toggled class, so the flash re-triggers cleanly on each click.
    el.animate?.(
        [
            { boxShadow: '0 0 0 3px var(--color-accent)' },
            { boxShadow: '0 0 0 3px var(--color-accent)', offset: 0.7 },
            { boxShadow: '0 0 0 3px transparent' },
        ],
        { duration: 1100, easing: 'ease-out' }
    )
}
