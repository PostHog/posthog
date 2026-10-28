/**
 * Unlayer has no supported option to start with the right-hand tools panel collapsed
 * (only `collapsible`), so this customJS runs inside the editor iframe and clicks the
 * panel's collapse toggle once on load. A collapsed panel also hides the selected block's
 * properties, such as a button's link, so selecting a block opens the panel again.
 * DOM-coupled by necessity: if unlayer renames `.collapse-tools-panel-button` or
 * `.blockbuilder-layer-selected`, the panel silently stays as it is (the retry loop bails
 * out after ~10s, nothing breaks).
 */
export const collapseToolsPanelCustomJs = `
(function () {
    var tries = 0
    var timer = setInterval(function () {
        tries += 1
        if (tries > 40) {
            clearInterval(timer)
            return
        }
        var toggle = document.querySelector('button.collapse-tools-panel-button')
        if (toggle) {
            clearInterval(timer)
            toggle.click()
            openPanelOnSelect()
        }
    }, 250)

    function openPanelOnSelect() {
        var lastSelected = null
        new MutationObserver(function () {
            var selected = document.querySelector('.blockbuilder-layer-selected')
            if (selected === lastSelected) {
                return
            }
            lastSelected = selected
            var toggle = document.querySelector('button.collapse-tools-panel-button.collapsed')
            if (selected && toggle) {
                // Opening the panel clears the selection, so select the block again to show its properties.
                toggle.click()
                setTimeout(function () {
                    // A block selected in the meantime is the newer choice, so keep it.
                    if (selected.isConnected && !document.querySelector('.blockbuilder-layer-selected')) {
                        ;['mousedown', 'mouseup', 'click'].forEach(function (type) {
                            selected.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, view: window }))
                        })
                    }
                }, 200)
            }
        }).observe(document.body, { subtree: true, attributes: true, attributeFilter: ['class'], childList: true })
    }
})()
`
