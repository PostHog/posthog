/**
 * Unlayer has no supported option to start with the right-hand tools panel collapsed
 * (only `collapsible`), so this customJS runs inside the editor iframe and clicks the
 * panel's collapse toggle once on load. DOM-coupled by necessity: if unlayer renames
 * `.collapse-tools-panel-button`, the panel silently stays open (the retry loop bails
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
        }
    }, 250)
})()
`
