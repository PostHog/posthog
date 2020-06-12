import { kea } from 'kea'
import { dockLogic } from '~/toolbar/dockLogic'
import { currentPageLogic } from '~/toolbar/stats/currentPageLogic'
import { elementToActionStep } from '~/toolbar/shared/utils'

const CLICK_TARGET_SELECTOR = `a, button, input, select, textarea, label`

// This trims the "hovered" DOM node down. For example:
// - div > div > div > svg > path  <--- ignore the path, just inpsect the full image/svg
// - div > div > button > span     <--- we probably care about the button, not the span
// - div > div > a > span          <--- same with links
const DOM_TRIM_DOWN_SELECTOR = 'a, svg, button'

function drawBox(box, element, zoom, padding) {
    if (!element) {
        box.style.display = 'none'
        return
    }

    const rect = element.getBoundingClientRect()
    box.style.display = 'block'
    box.style.position = 'absolute'
    box.style.top = `${(rect.top + window.pageYOffset - padding) / zoom}px`
    box.style.left = `${(rect.left + window.pageXOffset - padding) / zoom}px`
    box.style.width = `${(rect.right - rect.left) / zoom}px`
    box.style.height = `${(rect.bottom - rect.top) / zoom}px`
    box.style.boxShadow = 'hsl(207, 80%, 24%) 0px 3px 10px 4px'
    box.style.background = 'hsl(207, 90%, 54%)'
    box.style.backgroundBlendMode = 'multiply'
    box.style.opacity = '0.5'
    box.style.zIndex = '2147483010'
    box.style.pointerEvents = 'auto'
    box.style.cursor = 'pointer'
    box.style.transition = 'all ease 0.1s'
}

export const inspectElementLogic = kea({
    actions: () => ({
        start: true,
        stop: (clear = true) => ({ clear }),
        selectElement: element => ({ element }),
        hoverElement: element => ({ element }), // array of [dom elements]
        selectAllElements: true,
        selectClickTargets: true,
    }),

    reducers: () => ({
        selecting: [
            false,
            {
                start: () => true,
                stop: () => false,
            },
        ],
        hoveredElement: [
            null,
            {
                stop: (state, { clear }) => (clear ? null : state),
                hoverElement: (_, { element }) => element,
            },
        ],
        selectedElement: [
            null,
            {
                selectElement: (_, { element }) => element,
                start: () => null,
                stop: (state, { clear }) => (clear ? null : state),
            },
        ],
        selectingClickTargets: [
            false,
            {
                selectAllElements: () => false,
                selectClickTargets: () => true,
            },
        ],
    }),

    selectors: ({ selectors }) => ({
        baseElement: [
            () => [
                selectors.hoveredElement,
                selectors.selectedElement,
                selectors.selecting,
                selectors.selectingClickTargets,
            ],
            (hoveredElement, selectedElement, selecting, selectingClickTargets) => {
                let loopElement = selecting ? hoveredElement || selectedElement : selectedElement

                if (selectingClickTargets) {
                    while (loopElement?.parentElement) {
                        // return when we find a click target
                        if (loopElement.matches(CLICK_TARGET_SELECTOR)) {
                            return loopElement
                        }
                        loopElement = loopElement.parentElement
                    }
                    return null
                } else {
                    // selecting all elements
                    let selectedElement = loopElement
                    while (loopElement?.parentElement) {
                        // trim down the dom nodes
                        if (loopElement.matches(DOM_TRIM_DOWN_SELECTOR)) {
                            selectedElement = loopElement
                        }
                        loopElement = loopElement.parentElement
                    }
                    return selectedElement
                }
            },
        ],
        element: [
            () => [selectors.baseElement, currentPageLogic.selectors.href],
            (baseElement, href) => (baseElement && href && document.body.contains(baseElement) ? baseElement : null),
        ],
        actionStep: [() => [selectors.element], element => (element ? elementToActionStep(element) : null)],
    }),

    events: ({ cache, values, actions }) => ({
        afterMount: () => {
            cache.box = window.document.createElement('div')
            window.document.body.appendChild(cache.box)

            cache.onBoxClick = function onBoxClick() {
                actions.selectElement(values.hoveredElement)
            }
            cache.box.addEventListener('click', cache.onBoxClick)

            cache.onKeyDown = function onKeyDown(event) {
                // stop selecting if esc key was pressed
                if (event.keyCode === 27) {
                    if (values.selectedElement) {
                        actions.start()
                    } else if (values.selecting) {
                        actions.stop()
                    }
                }
            }
            window.addEventListener('keydown', cache.onKeyDown)

            cache.onMouseMove = function onMouseMove(event) {
                if (values.selecting) {
                    cache.box.style.pointerEvents = 'none'
                    const element = window.document.elementFromPoint(event.clientX, event.clientY)
                    cache.box.style.pointerEvents = 'auto'

                    if (values.element !== element) {
                        actions.hoverElement(element)
                    }
                }
            }
            window.document.body.addEventListener('mousemove', cache.onMouseMove) // , { capture: true })
        },
        beforeUnmount: () => {
            cache.box.removeEventListener('click', cache.onBoxClick)
            window.removeEventListener('keydown', cache.onKeyDown)
            window.document.body.removeEventListener('mousemove', cache.onMouseMove)
            if (values.inspecting) {
                actions.stop(true)
            }
            cache.box.remove()
        },
    }),

    listeners: ({ actions, cache, values }) => ({
        [currentPageLogic.actions.setHref]: () => {
            window.requestAnimationFrame(() => {
                if (!values.event && cache.box.style.display !== 'none') {
                    // cache.box.style.display = 'none'
                    actions.stop(true)
                }
            })
        },
        hoverElement: () => {
            drawBox(
                cache.box,
                values.element,
                dockLogic.values.mode === 'dock' ? dockLogic.values.zoom : 1,
                dockLogic.values.mode === 'dock' ? dockLogic.values.padding : 0
            )
        },
        selectElement: () => {
            drawBox(
                cache.box,
                values.element,
                dockLogic.values.mode === 'dock' ? dockLogic.values.zoom : 1,
                dockLogic.values.mode === 'dock' ? dockLogic.values.padding : 0
            )
            actions.stop(false)
        },
        stop: ({ clear }) => {
            if (clear) {
                cache.box.style.display = 'none'
            } else {
                cache.box.style.pointerEvents = 'none'
            }
        },
    }),
})
