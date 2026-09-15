export type GetHelpAction = () => void

/**
 * Where people without in-app support end up: self-hosted instances, the toolbar, the exporter.
 * The docs page lists the channels open to each plan; posthog.com/support sells the support product.
 */
export const openSupportOptions: GetHelpAction = () => {
    // `noopener` because window.open, unlike an <a target="_blank">, leaves window.opener reachable
    // by the opened page.
    window.open(
        'https://posthog.com/docs/support-options?utm_medium=in-product&utm_campaign=error-toast',
        '_blank',
        'noopener'
    )
}

let getHelpAction: GetHelpAction = openSupportOptions

/**
 * Replaces what the error toast's "Get help" button does. The app registers the in-product support
 * form in `bootApp()`; bundles without one (toolbar, exporter) keep the docs fallback.
 * A seam rather than a direct call because `supportLogic` already imports the toast module, so
 * reaching back into it from here would close a cycle.
 */
export function setGetHelpAction(action: GetHelpAction): void {
    getHelpAction = action
}

/** Restores the docs fallback. Test-only: keeps a registered action from leaking across tests. */
export function resetGetHelpAction(): void {
    getHelpAction = openSupportOptions
}

export function getHelp(): void {
    getHelpAction()
}
