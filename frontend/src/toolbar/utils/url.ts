export function joinWithUiHost(uiHost: string, path: string): string {
    const trimmedHost = (uiHost || '').replace(/\/+$/, '')
    const trimmedPath = (path || '').trim()

    if (!trimmedHost) {
        return trimmedPath
    }
    if (!trimmedPath) {
        return trimmedHost
    }

    // If a full URL is passed, don't try to join it.
    if (/^https?:\/\//i.test(trimmedPath) || /^\/\/[^/]/.test(trimmedPath)) {
        return trimmedPath
    }

    return `${trimmedHost}/${trimmedPath.replace(/^\/+/, '')}`
}
