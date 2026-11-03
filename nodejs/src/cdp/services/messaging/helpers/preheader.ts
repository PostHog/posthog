const BODY_OPEN_TAG = /<body\b[^>]*>/i

export const maybeAddPreheaderToEmail = (html: string, preheader?: string): string => {
    if (!preheader) {
        return html
    }

    const preheaderHtml = `<span style="display:none !important;visibility:hidden;mso-hide:all;font-size:1px;color:#ffffff;line-height:1px;max-height:0px;max-width:0px;opacity:0;overflow:hidden;">${preheader}</span>`
    // Inboxes take the preview from the first text in the body, so the hidden text goes right after
    // the opening body tag. HTML without one, such as a fragment saved through the API, gets it first.
    const bodyOpen = BODY_OPEN_TAG.exec(html)
    if (!bodyOpen) {
        return preheaderHtml + html
    }
    const insertAt = bodyOpen.index + bodyOpen[0].length
    return html.slice(0, insertAt) + preheaderHtml + html.slice(insertAt)
}
