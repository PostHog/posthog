import React from 'react'
import { inspectElementLogic } from '~/toolbar/shared/inspectElementLogic'
import { useActions, useValues } from 'kea'
import { dockLogic } from '~/toolbar/dockLogic'

export function InspectElementRect() {
    const { domZoom, domPadding } = useValues(dockLogic)
    const { element } = useValues(inspectElementLogic)
    const { selectElement } = useActions(inspectElementLogic)
    const rect = element.getBoundingClientRect()

    if (!element) {
        return null
    }

    return (
        <div
            id="toolbar-inspect-element-div"
            onClick={() => selectElement(element)}
            style={{
                display: 'block',
                position: 'absolute',
                top: `${(rect.top + window.pageYOffset - domPadding) / domZoom}px`,
                left: `${(rect.left + window.pageXOffset - domPadding) / domZoom}px`,
                width: `${(rect.right - rect.left) / domZoom}px`,
                height: `${(rect.bottom - rect.top) / domZoom}px`,
                boxShadow: 'hsl(207, 80%, 24%) 0px 3px 10px 4px',
                background: 'hsl(207, 90%, 54%)',
                backgroundBlendMode: 'multiply',
                opacity: '0.5',
                zIndex: '2147483010',
                pointerEvents: 'auto',
                cursor: 'pointer',
                transition: 'all ease 0.1s',
            }}
        />
    )
}
