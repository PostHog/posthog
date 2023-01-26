import { useActions, useValues } from 'kea'
import { CloseOutlined } from '@ant-design/icons'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { ElementInfo } from '~/toolbar/elements/ElementInfo'

export function InfoWindow(): JSX.Element | null {
    const { hoverElement, hoverElementMeta, selectedElement, selectedElementMeta } = useValues(elementsLogic)
    const { setSelectedElement } = useActions(elementsLogic)

    // use rectUpdateCounter to reload component when it changes, but discard the output
    useValues(elementsLogic).rectUpdateCounter

    const activeMeta = hoverElementMeta || selectedElementMeta

    if (!activeMeta || !activeMeta.rect) {
        return null
    }

    const pointerEvents = selectedElementMeta && (!hoverElement || hoverElement === selectedElement)
    const onClose =
        selectedElementMeta && activeMeta.element === selectedElementMeta.element
            ? () => setSelectedElement(null)
            : null
    const { rect } = activeMeta

    const windowWidth = Math.min(document.documentElement.clientWidth, window.innerWidth)
    const windowHeight = Math.min(document.documentElement.clientHeight, window.innerHeight)
    let positioningHeight = windowHeight
    if (getComputedStyle(document.body).position === 'relative') {
        // we have seen at least one client with position relative on the body
        // this breaks assumptions the info window makes about how to calculate
        // distance relative to the bottom of the window.
        // Always using document.body.clientHeight broke other sites, so we
        // only use it when we know it's necessary.
        positioningHeight = document.body.clientHeight
    }

    let left = rect.left + window.pageXOffset + (rect.width > 300 ? (rect.width - 300) / 2 : 0)
    let width = 300
    if (left + width > windowWidth - 10) {
        left -= left + width - (windowWidth - 10)
        if (left < 0) {
            left = 5
            width = windowWidth - 10
        }
    }

    let top: number | undefined = Math.max(window.pageYOffset + 16, rect.top + rect.height + 10 + window.pageYOffset)
    let bottom: number | undefined
    const minHeight: number | undefined = 50
    let maxHeight: number | undefined

    const spaceAbove = Math.max(minHeight, rect.top - 20)
    const spaceBelow = Math.max(minHeight, windowHeight - top + window.pageYOffset - 10)

    if (spaceAbove > spaceBelow) {
        top = undefined
        bottom = positioningHeight - rect.top + 10 - window.pageYOffset
        maxHeight = spaceAbove
    } else {
        maxHeight = spaceBelow
    }

    return (
        <div
            style={{
                pointerEvents: pointerEvents ? 'all' : 'none',
                position: 'absolute',
                top,
                bottom,
                left,
                width,
                minHeight,
                maxHeight,
                zIndex: 1,
                opacity: 1,
                transformOrigin: 'top left',
                transition: 'opacity 0.2s, box-shadow 0.2s',
                backgroundBlendMode: 'multiply',
                background: 'white',
                boxShadow: `hsla(4, 30%, 27%, 0.6) 0px 3px 10px 2px`,
            }}
        >
            {onClose ? (
                <div
                    onClick={onClose}
                    style={{
                        pointerEvents: pointerEvents ? 'all' : 'none',
                        position: 'absolute',
                        top: -8,
                        right: left + width > windowWidth - 20 ? -6 : -12,
                        transformOrigin: 'top left',
                        background: 'black',
                        color: 'white',
                        boxShadow: `hsla(4, 30%, 27%, 0.6) 0px 3px 10px 2px`,
                        borderRadius: '100%',
                        width: 24,
                        height: 24,
                        zIndex: 7,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-around',
                        textAlign: 'center',
                        cursor: 'pointer',
                    }}
                >
                    <CloseOutlined />
                </div>
            ) : null}
            <div style={{ minHeight, maxHeight, overflow: 'auto' }}>
                <ElementInfo />
            </div>
        </div>
    )
}
