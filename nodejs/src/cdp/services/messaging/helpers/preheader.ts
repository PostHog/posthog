export const addPreheaderToEmail = (html: string, preheader: string): string => {
    const preheaderHtml = `<span style="display:none !important;visibility:hidden;mso-hide:all;font-size:1px;color:#ffffff;line-height:1px;max-height:0px;max-width:0px;opacity:0;overflow:hidden;">${preheader}</span>`
    return html.replace('<tbody>', `<tbody>${preheaderHtml}`)
}
