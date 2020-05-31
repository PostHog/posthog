import React from 'react'
import { Button } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import { kea, useActions, useValues } from 'kea'
import { dockLogic } from '~/editor/dockLogic'

function drawBox(box, element, zoom, padding) {
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
    box.style.zIndex = '9999999999'
    box.style.pointerEvents = 'none'
    box.style.transition = 'all ease 0.1s'
}

// props:
// - zoom
const inspectElementLogic = kea({
    actions: () => ({
        start: true,
        stop: true,
        hoverElement: element => ({ element }), // array of [dom elements]
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
                hoverElement: (_, { element }) => element,
            },
        ],
    }),

    selectors: ({ selectors }) => ({
        element: [
            () => [selectors.hoveredElement],
            hoveredElement => {
                let selectedElement = hoveredElement
                let loopElement = hoveredElement
                while (loopElement?.parentElement) {
                    if (
                        loopElement.tagName.toLowerCase() === 'a' ||
                        loopElement.tagName.toLowerCase() === 'svg' ||
                        loopElement.tagName.toLowerCase() === 'button'
                    ) {
                        selectedElement = loopElement
                    }
                    loopElement = loopElement.parentElement
                }
                return selectedElement
            },
        ],
    }),

    events: ({ cache, values, actions }) => ({
        afterMount: () => {
            cache.box = document.createElement('div')
            document.body.appendChild(cache.box)
        },
        beforeUnmount: () => {
            if (values.inspecting) {
                actions.stop()
            }
            cache.box.remove()
        },
    }),

    listeners: ({ actions, cache, values }) => ({
        hoverElement: () => {
            // console.log(element)
            drawBox(cache.box, values.element, dockLogic.values.zoom, dockLogic.values.padding)
        },
        start: () => {
            cache.onMouseMove = function onMouseMove(event) {
                if (values.element !== event.target) {
                    actions.hoverElement(event.target)
                }
            }
            cache.onKeyDown = function onKeyDown(event) {
                // stop selecting if esc key was pressed
                if (event.keyCode === 27) actions.stop()
            }
            // cache.elements = document.querySelectorAll('a, button, input, select, textarea, label')
            // cache.elements.forEach(element => {
            //     element.addEventListener('mouseover', cache.onMouseOver, {
            //         capture: true,
            //     })
            // })

            window.document.body.addEventListener('mousemove', cache.onMouseMove, { capture: true })
            window.document.addEventListener('keydown', cache.onKeyDown)
            cache.box.addEventListener('click', actions.stop)
        },
        stop: () => {
            // document.querySelectorAll('a, button, input, select, textarea, label').forEach(element => {
            //     element.removeEventListener('mouseover', cache.onMouseOver, {
            //         capture: true,
            //     })
            // })
            window.document.body.removeEventListener('mousemove', cache.onMouseMove)
            document.removeEventListener('keydown', cache.onKeyDown)
            cache.box.removeEventListener('click', actions.stop)
            cache.box.style.display = 'none'
        },
    }),
})

export function ElementPath({ element }) {
    let path = []
    let currentElement = element
    let i = 0
    while (currentElement?.parentElement) {
        path.push(<div key={i++}>{currentElement.tagName}</div>)
        currentElement = currentElement.parentElement
    }

    return <>{path}</>
}

export function InspectElement() {
    const { selecting, element } = useValues(inspectElementLogic)
    const { stop, start } = useActions(inspectElementLogic)

    return (
        <div className="float-box">
            <Button type={selecting ? 'primary' : 'secondary'} onClick={selecting ? stop : start}>
                <SearchOutlined /> Select an element{' '}
            </Button>
            <div style={{ marginTop: 10 }}>
                {!selecting ? (
                    <small>... and see associated analytics here</small>
                ) : !element ? (
                    <small>Hover over the element to select it!</small>
                ) : (
                    <ElementPath element={element} />
                )}
            </div>
        </div>
    )
}
