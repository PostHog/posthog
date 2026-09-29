/**
 * Unlayer shows the preview in a nested iframe, so a link click navigates that iframe. Most sites
 * refuse to be framed, so an author who clicks a link to test it gets a broken page. A `<base>`
 * target is not enough: Unlayer writes `target="_self"` for "same tab" links, which overrides it.
 *
 * The editor's `unlayer` global has no `registerCallback`, so there is no hook for the preview
 * markup. The preview iframe is same-origin with the editor frame this runs in, so watch for it and
 * send each link click in it to a new tab. Only the click changes, so the design and the exported
 * email keep the author's target.
 */
export const previewLinkTargetCustomJs = `
(function () {
    function openLinksInNewTab(frameDocument) {
        if (!frameDocument || frameDocument.__posthogPreviewLinkTarget) {
            return
        }
        frameDocument.__posthogPreviewLinkTarget = true
        frameDocument.addEventListener(
            'click',
            function (event) {
                var link = event.target && event.target.closest ? event.target.closest('a[href]') : null
                if (link) {
                    link.setAttribute('target', '_blank')
                    link.setAttribute('rel', 'noopener noreferrer')
                }
            },
            true
        )
    }

    function watchFrame(frame) {
        if (frame.__posthogPreviewLinkTarget) {
            return
        }
        frame.__posthogPreviewLinkTarget = true
        function attach() {
            try {
                openLinksInNewTab(frame.contentDocument)
            } catch (e) {}
        }
        // The preview replaces its document whenever its content changes, so attach on every load.
        frame.addEventListener('load', attach)
        attach()
    }

    function watchFrames(root) {
        var frames = root.querySelectorAll ? root.querySelectorAll('iframe') : []
        for (var i = 0; i < frames.length; i++) {
            watchFrame(frames[i])
        }
        if (root.tagName === 'IFRAME') {
            watchFrame(root)
        }
    }

    function start() {
        watchFrames(document)
        new MutationObserver(function (mutations) {
            for (var i = 0; i < mutations.length; i++) {
                var added = mutations[i].addedNodes
                for (var j = 0; j < added.length; j++) {
                    if (added[j].nodeType === 1) {
                        watchFrames(added[j])
                    }
                }
            }
        }).observe(document.documentElement, { childList: true, subtree: true })
    }

    if (typeof document !== 'undefined' && typeof MutationObserver !== 'undefined') {
        start()
    }
})()
`
