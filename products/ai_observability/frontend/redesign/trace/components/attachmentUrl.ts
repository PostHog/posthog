export type AttachmentUrlKind = 'data' | 'sameOrigin' | 'external' | null

export function classifyAttachmentUrl(url: string | null): AttachmentUrlKind {
    if (!url) {
        return null
    }
    if (/^data:/i.test(url)) {
        return 'data'
    }
    // blob: never leaves the page's origin, same as a relative path. A path whose second
    // character is `/` or `\` is protocol-relative (browsers normalize `\` to `/` here too), so
    // the browser resolves it against an arbitrary host instead of the app.
    if (/^blob:/i.test(url) || /^\/(?![/\\])/.test(url)) {
        return 'sameOrigin'
    }
    if (/^https?:\/\//i.test(url)) {
        return 'external'
    }
    return null
}
