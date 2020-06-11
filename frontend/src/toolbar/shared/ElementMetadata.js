import React from 'react'
import { useValues } from 'kea'
import { dockLogic } from '~/toolbar/dockLogic'
import { ActionStep } from '~/toolbar/shared/ActionStep'
import { CloseOutlined } from '@ant-design/icons'
import { heatmapLogic } from '~/toolbar/shared/heatmapLogic'

export function ElementMetadata({ rect, meta: { actionStep, element: metaElement }, pointerEvents, onClose }) {
    const { domZoom, domPadding } = useValues(dockLogic)
    const { elementMap, eventCount } = useValues(heatmapLogic)

    const heatmapMeta = elementMap.get(metaElement)

    return (
        <>
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
                <div style={{ marginBottom: 10, paddingBottom: 10, borderBottom: '1px solid #eee' }}>
                    {heatmapMeta && eventCount !== 0 ? (
                        <div>
                            This element got {heatmapMeta.count} out of {eventCount} clicks ={' '}
                            {Math.round((heatmapMeta.count / eventCount) * 10000) / 100}%
                        </div>
                    ) : (
                        <div>No clicks recorded for this element</div>
                    )}
                </div>
                <ActionStep actionStep={actionStep} />
            </div>
            {onClose ? (
                <div
                    onClick={onClose}
                    style={{
                        pointerEvents: pointerEvents ? 'all' : 'none',
                        position: 'absolute',
                        top: `${(rect.top + rect.height - domPadding - 2 + window.pageYOffset) / domZoom}px`,
                        left: `${(rect.left -
                            domPadding +
                            window.pageXOffset +
                            288 +
                            (rect.width > 300 ? (rect.width - 300) / 2 : 0)) /
                            domZoom}px`,
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
