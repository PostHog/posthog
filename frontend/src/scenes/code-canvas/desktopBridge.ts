/** Sends the browser to a `posthog-code(-dev)://` deep link, which hands off to PostHog Desktop. */
export function openInDesktop(deepLink: string): void {
    window.location.href = deepLink
}

/** The explanation on a desktop bridge page. Both the Lemon and the quill view show it. */
export function desktopBridgeDescription(subject: string, hasWebView: boolean): string {
    return hasWebView
        ? `${subject} should open in the PostHog Desktop app if it's installed. You can also open it in your browser.`
        : `${subject} lives in the PostHog Desktop app. If it's installed, it should open automatically. If it didn't, use the button below, or download the app.`
}
