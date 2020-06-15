import { kea } from 'kea'
import { currentPageLogic } from '~/toolbar/stats/currentPageLogic'
import { elementToActionStep, getAllClickTargets, getShadowRoot, trimElement } from '~/toolbar/shared/utils'

export const inspectElementLogic = kea({
    actions: () => ({
        addClick: true,
        start: true,
        stop: (clear = true) => ({ clear }),
        selectElement: element => ({ element }),
        hoverElement: element => ({ element }), // array of [dom elements]
        selectAllElements: true,
        selectClickTargets: true,
    }),

    reducers: () => ({
        clicks: [
            0,
            {
                addClick: state => state + 1,
            },
        ],
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
            true,
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
                let element = selecting ? hoveredElement || selectedElement : selectedElement
                return trimElement(element, selectingClickTargets)
            },
        ],
        element: [
            () => [selectors.baseElement, currentPageLogic.selectors.href],
            (baseElement, href) => (baseElement && href && document.body.contains(baseElement) ? baseElement : null),
        ],
        actionStep: [() => [selectors.element], element => (element ? elementToActionStep(element) : null)],
        selectableElements: [
            () => [selectors.selecting, selectors.selectingClickTargets, selectors.selectedElement],
            (selecting, selectingClickTargets, selectedElement) =>
                (selecting || selectedElement) && selectingClickTargets ? getAllClickTargets() : [],
        ],
        selectableElementsWithRects: [
            () => [selectors.selectableElements, selectors.clicks],
            selectableElements =>
                selectableElements.map(element => ({
                    element,
                    rect: element.getBoundingClientRect(),
                    count: 0,
                    type: 'inspect',
                })),
        ],
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

            cache.onClick = function() {
                actions.addClick()
            }
            cache.onClickAndDelay = function() {
                window.clearTimeout(cache.clickDelayTimeout)
                actions.addClick()
                cache.clickDelayTimeout = window.setTimeout(actions.addClick, 100)
            }
            window.addEventListener('click', cache.onClick)
            window.addEventListener('scroll', cache.onClickAndDelay)
        },
        beforeUnmount: () => {
            window.removeEventListener('keydown', cache.keyDown)
            window.removeEventListener('click', cache.onClick)
            window.removeEventListener('scroll', cache.onClickAndDelay)
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
