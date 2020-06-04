import { kea } from 'kea'
import { dockLogic } from '~/toolbar/dockLogic'
import Simmer from 'simmerjs'
import { currentPageLogic } from '~/toolbar/stats/currentPageLogic'

const CLICK_TARGET_SELECTOR = `a, button, input, select, textarea, label`

// This trims the "hovered" DOM node down. For example:
// - div > div > div > svg > path  <--- ignore the path, just inpsect the full image/svg
// - div > div > button > span     <--- we probably care about the button, not the span
// - div > div > a > span          <--- same with links
const DOM_TRIM_DOWN_SELECTOR = 'a, svg, button'

const simmer = new Simmer(window, { depth: 8 })

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
    box.style.boxShadow = '0 0 20px hsla(220, 92%, 65%, 1)'
    box.style.background = 'hsla(220, 92%, 65%, 1)'
    box.style.backgroundBlendMode = 'multiply'
    box.style.opacity = '0.5'
    box.style.zIndex = '2147483630'
    box.style.pointerEvents = 'auto'
    box.style.cursor = 'pointer'
    box.style.transition = 'all ease 0.1s'
}

const getSafeText = el => {
    if (!el.childNodes || !el.childNodes.length) return
    let elText = ''
    el.childNodes.forEach(child => {
        if (child.nodeType !== 3 || !child.textContent) return
        elText += child.textContent
            .trim()
            .replace(/[\r\n]/g, ' ')
            .replace(/[ ]+/g, ' ') // normalize whitespace
            .substring(0, 255)
    })
    return elText
}

// function elementToSelection(element) {
//     const tagName = element.tagName.toLowerCase()
//
//     return tagName === 'a'
//         ? ['href', 'selector']
//         : tagName === 'button'
//         ? ['text', 'selector']
//         : element.getAttribute('name')
//         ? ['name', 'selector']
//         : ['selector']
// }

function elementToQuery(element) {
    if (!element) {
        return null
    }
    return (
        simmer(element)
            // Turn tags into lower cases
            .replace(/(^[A-Z]+| [A-Z]+)/g, d => d.toLowerCase())
    )
}

function elementToActionStep(element) {
    let query = elementToQuery(element)
    const tagName = element.tagName.toLowerCase()

    return {
        event: '$autocapture',
        tag_name: tagName,
        href: element.getAttribute('href') || '',
        name: element.getAttribute('name') || '',
        text: getSafeText(element) || '',
        selector: query || '',
        url: window.location.protocol + '//' + window.location.host + window.location.pathname,
    }
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
        },
        beforeUnmount: () => {
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
            drawBox(cache.box, values.element, dockLogic.values.zoom, dockLogic.values.padding)
        },
        selectElement: () => {
            drawBox(cache.box, values.element, dockLogic.values.zoom, dockLogic.values.padding)
            actions.stop(false)
        },
        start: () => {
            cache.onMouseMove = function onMouseMove(event) {
                cache.box.style.pointerEvents = 'none'
                const element = window.document.elementFromPoint(event.clientX, event.clientY)
                cache.box.style.pointerEvents = 'auto'

                if (values.element !== element) {
                    actions.hoverElement(element)
                }
            }
            cache.onKeyDown = function onKeyDown(event) {
                // stop selecting if esc key was pressed
                if (event.keyCode === 27) {
                    actions.stop()
                }
            }
            cache.onClick = function onClick() {
                actions.selectElement(values.hoveredElement)
            }

            window.document.body.addEventListener('mousemove', cache.onMouseMove) // , { capture: true })
            window.document.addEventListener('keydown', cache.onKeyDown)
            cache.box.addEventListener('click', cache.onClick)
        },
        stop: ({ clear }) => {
            window.document.body.removeEventListener('mousemove', cache.onMouseMove)
            document.removeEventListener('keydown', cache.onKeyDown)
            cache.box.removeEventListener('click', cache.onClick)
            if (clear) {
                cache.box.style.display = 'none'
            } else {
                cache.box.style.pointerEvents = 'none'
            }
        },
    }),
})
