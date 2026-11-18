/**
 * Unlayer shows the preview in a nested iframe, so a link that has no target navigates that
 * iframe. Most sites refuse to be framed, so an author who clicks a link to test it gets a
 * broken page. `previewHtml` is Unlayer's documented hook for the markup that preview mode
 * shows: give that markup a default target and the clicks open a new tab. The base tag has
 * no href, so relative URLs resolve as before, and the exported email does not change.
 */
export const previewLinkTargetCustomJs = `
if (typeof unlayer !== 'undefined' && unlayer.registerCallback) {
    unlayer.registerCallback('previewHtml', function (params, done) {
        var html = params && params.html ? params.html : ''
        var baseTag = '<base target="_blank">'
        var headStart = html.indexOf('<head')
        var headTagEnd = headStart === -1 ? -1 : html.indexOf('>', headStart)
        done({
            html:
                headTagEnd === -1
                    ? baseTag + html
                    : html.slice(0, headTagEnd + 1) + baseTag + html.slice(headTagEnd + 1),
        })
    })
}
`
