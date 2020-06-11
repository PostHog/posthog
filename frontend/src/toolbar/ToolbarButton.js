import './ToolbarButton.scss'

import React, { useState, useRef, useEffect } from 'react'
import { useActions } from 'kea'
import { useLongPress } from 'lib/hooks/useLongPress'
import { CloseOutlined, ProfileOutlined } from '@ant-design/icons'
import { Tooltip } from 'antd'
import { Logo } from '~/toolbar/assets/Logo'
import { Circle } from '~/toolbar/shared/Circle'

const quarters = { ne: 0, nw: 1, sw: 2, se: 3 }

function getQuarterRotation({ itemCount, index, quarter, padding: inputPadding }) {
    const padding = typeof inputPadding !== 'undefined' ? inputPadding : 90 / itemCount
    const angle = quarter * 90 + padding / 2 + ((90 - padding) / (itemCount - 1)) * index
    return -angle
}

export function ToolbarButton({ dockLogic, shadowRef }) {
    const { dock, float, hideButton } = useActions(dockLogic)

    const [quarter, setQuarter] = useState('ne')
    const [buttonsExtended, setButtonsExtended] = useState(false)

    const timeoutRef = useRef(null)

    function setQuarterFromShadowRef(shadowRef) {
        if (shadowRef.current) {
            const element = shadowRef.current.shadowRoot.getElementById('button-toolbar')
            if (element) {
                const rect = element.getBoundingClientRect()
                const x = rect.x + rect.width / 2
                const y = rect.y + rect.height / 2
                const ns = y < window.innerHeight / 2 ? 's' : 'n'
                const we = x < window.innerWidth / 2 ? 'e' : 'w'
                if (quarter !== `${ns}${we}`) {
                    setQuarter(`${ns}${we}`)
                }
            }
        }
    }

    useEffect(() => {
        setQuarterFromShadowRef(shadowRef)
    }, [])

    function extendButtons() {
        window.clearTimeout(timeoutRef.current)
        if (!buttonsExtended) {
            setButtonsExtended(true)
        }
    }

    function onMouseMove() {
        setQuarterFromShadowRef(shadowRef)
        extendButtons()
    }

    function onMouseLeave() {
        timeoutRef.current = window.setTimeout(() => setButtonsExtended(false), 400)
    }

    const longPressEvents = useLongPress(
        clicked => {
            setQuarterFromShadowRef(shadowRef)

            if (clicked) {
                dock()
            } else {
                extendButtons()
            }
        },
        { ms: 700, clickMs: 1 }
    )

    return (
        <>
            <Circle
                rootNode
                radius={64}
                className="floating-toolbar-button"
                content={
                    <Tooltip
                        title="Launch Toolbar"
                        placement={quarter.includes('n') ? 'bottom' : 'top'}
                        getPopupContainer={() => shadowRef.current.shadowRoot}
                    >
                        <Logo style={{ width: 54, height: 54, filter: 'invert(1)', cursor: 'pointer' }} />
                    </Tooltip>
                }
                {...longPressEvents}
                onMouseMove={e => {
                    onMouseMove(e)
                    longPressEvents.onMouseMove(e)
                }}
                onMouseLeave={e => {
                    onMouseLeave(e)
                    longPressEvents.onMouseLeave(e)
                }}
                zIndex={3}
            >
                <Circle
                    radius={32}
                    distance={buttonsExtended ? 70 : 0}
                    rotate={getQuarterRotation({ itemCount: 2, index: 0, padding: 30, quarter: quarters[quarter] })}
                    content={
                        <Tooltip
                            title="Floating Toolbar"
                            placement={quarter.includes('e') ? 'right' : 'left'}
                            getPopupContainer={() => shadowRef.current.shadowRoot}
                        >
                            <ProfileOutlined />
                        </Tooltip>
                    }
                    zIndex={1}
                    onMouseMove={onMouseMove}
                    onMouseLeave={onMouseLeave}
                    onClick={float}
                    style={{ cursor: 'pointer' }}
                />
                <Circle
                    radius={32}
                    distance={buttonsExtended ? 70 : 0}
                    rotate={getQuarterRotation({ itemCount: 2, index: 1, padding: 30, quarter: quarters[quarter] })}
                    content={
                        <Tooltip
                            title="Hide"
                            placement={quarter.includes('e') ? 'right' : 'left'}
                            getPopupContainer={() => shadowRef.current.shadowRoot}
                        >
                            <CloseOutlined />
                        </Tooltip>
                    }
                    zIndex={1}
                    onMouseMove={onMouseMove}
                    onMouseLeave={onMouseLeave}
                    onClick={hideButton}
                    style={{ cursor: 'pointer' }}
                />
            </Circle>
        </>
    )
}
