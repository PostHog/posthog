import { kea } from 'kea'
import { currentPageLogic } from '~/toolbar/stats/currentPageLogic'
import { elementToActionStep, getShadowRoot } from '~/toolbar/shared/utils'

const CLICK_TARGET_SELECTOR = `a, button, input, select, textarea, label`

// This trims the "hovered" DOM node down. For example:
// - div > div > div > svg > path  <--- ignore the path, just inpsect the full image/svg
// - div > div > button > span     <--- we probably care about the button, not the span
// - div > div > a > span          <--- same with links
const DOM_TRIM_DOWN_SELECTOR = 'a, svg, button'

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
                selectElement: () => false,
            },
        ],
        hoveredElement: [
            null,
            {
                selectElement: () => null,
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
                    const inspectDiv = getShadowRoot()?.getElementById('toolbar-inspect-element-div')

                    if (inspectDiv) {
                        inspectDiv.style.pointerEvents = 'none'
                    }

                    const element = window.document.elementFromPoint(event.clientX, event.clientY)

                    if (inspectDiv) {
                        inspectDiv.style.pointerEvents = 'auto'
                    }

                    if (values.element !== element) {
                        actions.hoverElement(element)
                    }
                }
            }
            window.document.body.addEventListener('mousemove', cache.onMouseMove) // , { capture: true })
        },
        beforeUnmount: () => {
            window.removeEventListener('keydown', cache.onKeyDown)
            window.document.body.removeEventListener('mousemove', cache.onMouseMove)
            if (values.inspecting) {
                actions.stop(true)
            }
        },
    }),

    listeners: ({ actions, values }) => ({
        [currentPageLogic.actions.setHref]: () => {
            window.requestAnimationFrame(() => {
                if (!values.event && values.selecting) {
                    actions.stop(true)
                }
            })
        },
    }),
})
