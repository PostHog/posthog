export function withInertLinks(html: string | undefined): string | undefined {
    if (!html) {
        return html
    }
    const doc = new DOMParser().parseFromString(html, 'text/html')
    doc.querySelectorAll('a, area').forEach((link) => link.setAttribute('target', '_blank'))
    const doctype = doc.doctype ? new XMLSerializer().serializeToString(doc.doctype) : ''
    return doctype + doc.documentElement.outerHTML
}
