import React from 'react'
import { useValues } from 'kea'
import { dockLogic } from '~/toolbar/dockLogic'
import { ActionStep } from '~/toolbar/shared/ActionStep'

export function ElementMetadata({ rect, meta: { actionStep }, pointerEvents }) {
    const { domZoom, domPadding } = useValues(dockLogic)

    return (
        <div
            style={{
                pointerEvents: pointerEvents ? 'all' : 'none',
                position: 'absolute',
                top: `${(rect.top + rect.height - domPadding + 10 + window.pageYOffset) / domZoom}px`,
                left: `${(rect.left -
                    domPadding +
                    window.pageXOffset +
                    (rect.width > 300 ? (rect.width - 300) / 2 : 0)) /
                    domZoom}px`,
                width: `${300 / domZoom}px`,
                minHeight: `${100 / domZoom}px`,
                zIndex: 6,
                opacity: pointerEvents ? 1 : 0.9,
                transition: 'opacity 0.2s, box-shadow 0.2s',
                backgroundBlendMode: 'multiply',
                background: 'white',
                padding: 15,
                boxShadow: `hsla(4, 30%, 27%, 0.6) 0px 3px 10px 2px`,
            }}
        >
            <ActionStep actionStep={actionStep} />
        </div>
    )
}
