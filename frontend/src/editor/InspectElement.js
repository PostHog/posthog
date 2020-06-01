import React from 'react'
import { Button, Checkbox } from 'antd'
import {
    SearchOutlined,
    AimOutlined,
    FontSizeOutlined,
    LinkOutlined,
    FormOutlined,
    CodeOutlined,
} from '@ant-design/icons'
import { kea, useActions, useValues } from 'kea'
import { dockLogic } from '~/editor/dockLogic'
import Simmer from 'simmerjs'

const CLICK_TARGET_SELECTOR = `a, button, input, select, textarea, label`

// This trims the "hovered" DOM node down. For example:
// - div > div > div > svg > path  <--- ignore the path, just inpsect the full image/svg
// - div > div > button > span     <--- we probably care about the button, not the span
// - div > div > a > span          <--- same with links
const DOM_TRIM_DOWN_SELECTOR = 'a, svg, button'

const simmer = new Simmer(window, { depth: 8 })

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

// props:
// - zoom
const inspectElementLogic = kea({
    actions: () => ({
        start: true,
        stop: true,
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
                hoverElement: (_, { element }) => element,
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
        element: [
            () => [selectors.hoveredElement, selectors.selectingClickTargets],
            (hoveredElement, selectingClickTargets) => {
                if (selectingClickTargets) {
                    let loopElement = hoveredElement
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
                    let selectedElement = hoveredElement
                    let loopElement = hoveredElement
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
        actionStep: [() => [selectors.element], element => (element ? elementToActionStep(element) : null)],
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
                // const element = window.document.elementFromPoint(event.clientX, event.clientY)
                // console.log(element === event.target ? '!!' : '??')

                if (values.element !== event.target) {
                    actions.hoverElement(event.target)
                }
            }
            cache.onKeyDown = function onKeyDown(event) {
                // stop selecting if esc key was pressed
                if (event.keyCode === 27) {
                    actions.stop()
                }
            }
            // cache.elements = document.querySelectorAll('a, button, input, select, textarea, label')
            // cache.elements.forEach(element => {
            //     element.addEventListener('mouseover', cache.onMouseOver, {
            //         capture: true,
            //     })
            // })
            console.log('starting')

            window.document.body.addEventListener('mousemove', cache.onMouseMove) // , { capture: true })
            window.document.addEventListener('keydown', cache.onKeyDown)
            cache.box.addEventListener('click', actions.stop)
        },
        stop: () => {
            // document.querySelectorAll('a, button, input, select, textarea, label').forEach(element => {
            //     element.removeEventListener('mouseover', cache.onMouseOver, {
            //         capture: true,
            //     })
            // })
            console.log('stopping!')
            window.document.body.removeEventListener('mousemove', cache.onMouseMove)
            document.removeEventListener('keydown', cache.onKeyDown)
            cache.box.removeEventListener('click', actions.stop)
            cache.box.style.display = 'none'
        },
    }),
})

function ActionAttribute({ attribute, value }) {
    const icon =
        attribute === 'text' ? (
            <FontSizeOutlined />
        ) : attribute === 'href' ? (
            <LinkOutlined />
        ) : attribute === 'selector' ? (
            <CodeOutlined />
        ) : (
            <FormOutlined />
        )

    const text =
        attribute === 'href' ? (
            <a href={value} target="_blank" rel="noopener noreferrer">
                {value}
            </a>
        ) : attribute === 'selector' ? (
            <span style={{ fontFamily: 'monospace' }}>{value}</span>
        ) : (
            value
        )

    return (
        <div key={attribute} style={{ marginBottom: 10, paddingLeft: 24, position: 'relative' }}>
            <div style={{ position: 'absolute', left: 2, top: 3, color: 'hsl(240, 14%, 50%)' }}>{icon}</div>
            <span>{text}</span>
        </div>
    )
}

export function InspectElement() {
    const { selecting, element, selectingClickTargets, actionStep } = useValues(inspectElementLogic)
    const { stop, start, selectAllElements, selectClickTargets } = useActions(inspectElementLogic)

    return (
        <div className="float-box">
            <div style={{ fontSize: 16, marginBottom: 10 }}>
                <SearchOutlined /> Select an element
            </div>
            <div>
                <Button type={selecting ? 'primary' : 'secondary'} onClick={selecting ? stop : start}>
                    <AimOutlined />
                </Button>
                <span style={{ marginLeft: 20, display: selecting ? 'inline-block' : 'none' }}>
                    <Checkbox
                        checked={selectingClickTargets}
                        onClick={selectingClickTargets ? selectAllElements : selectClickTargets}
                    >
                        {' '}
                        Links Only
                    </Checkbox>
                </span>
            </div>
            <div style={{ marginTop: 10 }}>
                {element ? (
                    <div style={{ marginTop: 10 }}>
                        <div style={{ fontSize: 16, marginBottom: 10 }}>&lt;{actionStep.tag_name}&gt;</div>
                        {['text', 'name', 'href', 'selector'].map(attr =>
                            actionStep[attr] ? (
                                <ActionAttribute key={attr} attribute={attr} value={actionStep[attr]} />
                            ) : null
                        )}
                    </div>
                ) : null}
            </div>
        </div>
    )
}
