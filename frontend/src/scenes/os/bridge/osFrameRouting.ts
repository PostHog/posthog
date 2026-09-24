import { removeProjectIdIfPresent } from 'lib/utils/kea-router'

import { osFrameSrc } from './osFrame'

export interface OsLinkClick {
    href: string
    target: string
    download: boolean
    button: number
    metaKey: boolean
    ctrlKey: boolean
    shiftKey: boolean
    altKey: boolean
}

export type OsLinkTarget =
    /** Open the app path in another OS window. */
    | { kind: 'new-window'; path: string }
    /** Open the URL in a browser tab, because another site cannot load in a window. */
    | { kind: 'new-tab'; url: string }
    /** Load the URL in the whole browser tab, because the page refuses to load in a frame. */
    | { kind: 'top'; url: string }

// Server pages answer with a redirect to another site (SSO, OAuth, the toolbar) or are not part of the app,
// so they never load inside a window. Keep in sync with the non-API routes in `posthog/urls.py`.
const SERVER_PATH =
    /^\/(?:(?:admin|complete|oauth|toolbar_oauth|authorize_and_redirect|reauth|integrations\/connect)\/|(?:login|logout|signup|exporter|render_query)(?:\/|$))/

// An API URL that the app loads as a page, not with fetch, is a redirect (an OAuth start) or a file. Files
// download fine inside a frame, so only the redirects leave the window.
function isApiRedirect(url: URL): boolean {
    return url.pathname.startsWith('/api/') && !url.searchParams.has('download')
}

function isServerPath(pathname: string): boolean {
    return SERVER_PATH.test(pathname)
}

function parseHttpUrl(href: string, base: string): URL | null {
    try {
        const url = new URL(href, base)
        return url.protocol === 'http:' || url.protocol === 'https:' ? url : null
    } catch {
        return null
    }
}

function asksForNewTab({ target, button, metaKey, ctrlKey }: OsLinkClick): boolean {
    const blankTarget = !!target && !['_self', '_top', '_parent'].includes(target)
    return blankTarget || button === 1 || metaKey || ctrlKey
}

/**
 * Decides where a link click inside an OS window goes. Null means the app and the browser handle the
 * click as they would without the OS: in-app links then navigate inside the same window.
 */
export function osLinkTarget(click: OsLinkClick, currentHref: string): OsLinkTarget | null {
    if (!click.href || click.download || click.shiftKey || click.altKey || click.button > 1) {
        return null
    }
    const url = parseHttpUrl(click.href, currentHref)
    if (!url) {
        return null
    }
    const newTab = asksForNewTab(click)
    if (url.origin !== new URL(currentHref).origin) {
        // A browser tab already opens for a target or a modifier, so only a plain click needs help.
        return newTab ? null : { kind: 'new-tab', url: url.href }
    }
    if (isServerPath(url.pathname)) {
        return newTab ? null : { kind: 'top', url: url.href }
    }
    // An API link is a file or an OAuth start. The browser handles files, and `osNavigationTarget` catches the redirects.
    if (url.pathname.startsWith('/api/')) {
        return null
    }
    if (!newTab) {
        return null
    }
    const path = osFrameSrc(url, url.origin)
    return path ? { kind: 'new-window', path } : null
}

/**
 * Decides whether a page load that the frame starts itself (a redirect in code, a form post) must leave
 * the window. Returns the URL to load in the whole browser tab, or null to let the frame load it.
 */
export function osNavigationTarget(destination: string, origin: string): string | null {
    const url = parseHttpUrl(destination, origin)
    if (!url) {
        return null
    }
    return url.origin !== origin || isServerPath(url.pathname) || isApiRedirect(url) ? url.href : null
}

export interface OsParsedHref {
    pathname: string
    params: URLSearchParams
}

/** An app path without its project id or trailing slash, and its query. */
export function parseOsHref(href: string): OsParsedHref {
    const url = new URL(removeProjectIdIfPresent(href), 'http://os.invalid')
    return { pathname: url.pathname.replace(/\/+$/, '') || '/', params: url.searchParams }
}

/**
 * True when a URL shows the page at `href`: the same path, and every query value of `href`. Other query
 * values in the URL, such as filters, do not matter.
 */
export function osPathShowsPage(path: string, href: string): boolean {
    const current = parseOsHref(path)
    const page = parseOsHref(href)
    return (
        current.pathname === page.pathname &&
        [...page.params.entries()].every(([key, value]) => current.params.get(key) === value)
    )
}
