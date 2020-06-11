import React from 'react'
import { useValues } from 'kea'
import { dockLogic } from '~/toolbar/dockLogic'
import { ActionStep } from '~/toolbar/shared/ActionStep'

export function ElementMetadata({ rect, meta }) {
    const { domZoom, domPadding } = useValues(dockLogic)

    return (
        <div
            style={{
                pointerEvents: 'none',
                position: 'absolute',
                top: `${(rect.top + rect.height - domPadding + 10 + window.pageYOffset) / domZoom}px`,
                left: `${(rect.left - domPadding + window.pageXOffset) / domZoom}px`,
                width: `${300 / domZoom}px`,
                minHeight: `${100 / domZoom}px`,
                zIndex: 4,
                opacity: 1,
                transition: 'opacity 0.2s, box-shadow 0.2s',
                cursor: 'pointer',
                backgroundBlendMode: 'multiply',
                background: 'white',
                padding: 15,
                boxShadow: `hsla(4, 30%, 27%, 0.6) 0px 3px 10px 2px`,
            }}
        >
            <ActionStep actionStep={meta.actionStep} />
        </div>
    )
}
