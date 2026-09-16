export interface ClassicEmbedContext {
    parentOrigin: string
    projectId: string
}

export function getClassicEmbedContext(location: URL, framed: boolean): ClassicEmbedContext | null {
    if (!framed || location.searchParams.get('__desktop_classic') !== '1') {
        return null
    }
    const parentOrigin = location.searchParams.get('__desktop_parent_origin')
    const projectId = location.pathname.match(/^\/project\/(\d+)(?:\/|$)/)?.[1]
    const trustedOrigins = [location.origin, 'https://posthog.com', 'https://preview.posthog.com']
    if (location.hostname === 'localhost' || location.hostname.endsWith('.dev.posthog.dev')) {
        trustedOrigins.push('http://localhost:5273')
    }
    return parentOrigin && projectId && trustedOrigins.includes(parentOrigin) ? { parentOrigin, projectId } : null
}

export const classicEmbedContext = getClassicEmbedContext(
    new URL(window.location.href),
    window.parent !== window || /Electron\//.test(window.navigator.userAgent)
)

export function isClassicEmbedPath(pathname: string, projectId: string): boolean {
    const match = pathname.match(/^\/project\/(\d+)(?:\/([^/]*))?(?:\/|$)/)
    return match?.[1] === projectId && !['ai', 'max', 'chat', 'code'].includes(match[2] ?? '')
}
