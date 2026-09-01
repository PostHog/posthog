export type GetHelpAction = () => void

/** Where people without in-app support end up: self-hosted instances, the toolbar, the exporter. */
export const openSupportPage: GetHelpAction = () => {
    window.open('https://posthog.com/support?utm_medium=in-product&utm_campaign=error-toast', '_blank')
}

let getHelpAction: GetHelpAction = openSupportPage

/**
 * Replaces what the error toast's "Get help" button does. The app registers the in-product support
 * form in `bootApp()`; bundles without one (toolbar, exporter) keep the posthog.com fallback.
 * A seam rather than a direct call because `supportLogic` already imports the toast module, so
 * reaching back into it from here would close a cycle.
 */
export function setGetHelpAction(action: GetHelpAction): void {
    getHelpAction = action
}

/** Restores the posthog.com fallback. Test-only: keeps a registered action from leaking across tests. */
export function resetGetHelpAction(): void {
    getHelpAction = openSupportPage
}

export function getHelp(): void {
    getHelpAction()
}
