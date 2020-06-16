import React from 'react'
import { useActions, useValues } from 'kea'
import { dockLogic } from '~/toolbar/dockLogic'
import { CloseOutlined } from '@ant-design/icons'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { ElementInfo } from '~/toolbar/elements/ElementInfo'

export function HeatmapInfoWindow() {
    const { domZoom, domPadding } = useValues(dockLogic)
    const { hoverElement, hoverElementMeta, selectedElement, selectedElementMeta, hoverElementHighlight } = useValues(
        elementsLogic
    )
    const { setSelectedElement } = useActions(elementsLogic)

    const activeMeta = hoverElementMeta || selectedElementMeta

    if (hoverElementHighlight || !activeMeta) {
        return null
    }

    const pointerEvents = selectedElementMeta && (!hoverElement || hoverElement === selectedElement)
    const onClose =
        selectedElementMeta && activeMeta.element === selectedElementMeta.element
            ? () => setSelectedElement(null)
            : null
    const { rect } = activeMeta

    let top = rect.top + rect.height + 10 + window.pageYOffset
    let left = rect.left + window.pageXOffset + (rect.width > 300 ? (rect.width - 300) / 2 : 0)
    let width = 300

    if (left + width > window.innerWidth - 10) {
        left -= left + width - (window.innerWidth - 10)
        if (left < 0) {
            left = 5
            width = window.innerWidth - 10
        }
    }

    return (
        <>
            <div
                style={{
                    pointerEvents: pointerEvents ? 'all' : 'none',
                    position: 'absolute',
                    top: `${(top - domPadding) / domZoom}px`,
                    left: `${(left - domPadding) / domZoom}px`,
                    width: width,
                    minHeight: 100,
                    zIndex: 6,
                    opacity: 1,
                    transform: domZoom !== 1 ? `scale(${1 / domZoom})` : '',
                    transformOrigin: 'top left',
                    transition: 'opacity 0.2s, box-shadow 0.2s',
                    backgroundBlendMode: 'multiply',
                    background: 'white',
                    padding: 15,
                    boxShadow: `hsla(4, 30%, 27%, 0.6) 0px 3px 10px 2px`,
                }}
            >
                <ElementInfo />
            </div>
            {onClose ? (
                <div
                    onClick={onClose}
                    style={{
                        pointerEvents: pointerEvents ? 'all' : 'none',
                        position: 'absolute',
                        top: `${(top - 12 - domPadding) / domZoom}px`,
                        left: `${(left + width - (left + width > window.innerWidth - 20 ? 20 : 12) - domPadding) /
                            domZoom}px`,
                        transform: domZoom !== 1 ? `scale(${1 / domZoom})` : '',
                        transformOrigin: 'top left',
                        background: 'black',
                        color: 'white',
                        boxShadow: `hsla(4, 30%, 27%, 0.6) 0px 3px 10px 2px`,
                        borderRadius: '100%',
                        width: 24,
                        height: 24,
                        zIndex: 7,
                        lineHeight: '24px',
                        textAlign: 'center',
                        cursor: 'pointer',
                    }}
                >
                    <CloseOutlined />
                </div>
            ) : null}
        </>
    )
}
