import './ToolbarButton.scss'

import React, { useState, useRef, useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { useLongPress } from 'lib/hooks/useLongPress'
import { CloseOutlined, ProfileOutlined, SearchOutlined, FireFilled } from '@ant-design/icons'
import { Tooltip } from 'antd'
import { Logo } from '~/toolbar/assets/Logo'
import { Circle } from '~/toolbar/shared/Circle'
import { inspectElementLogic } from '~/toolbar/shared/inspectElementLogic'

const quarters = { ne: 0, nw: 1, sw: 2, se: 3 }

function getQuarterRotation({ itemCount, index, quarter, padding: inputPadding }) {
    const padding = typeof inputPadding !== 'undefined' ? inputPadding : 90 / itemCount
    const angle = quarter * 90 + (itemCount === 1 ? 45 : padding / 2 + ((90 - padding) / (itemCount - 1)) * index)
    // const angle = quarter * 90 + padding / 2 + ((90 - padding) / (itemCount - 1)) * index
    return -angle
}

function reverseQuarter(quarter) {
    return (quarter[0] === 'n' ? 's' : 'n') + (quarter[1] === 'e' ? 'w' : 'e')
}

export function ToolbarButton({ dockLogic, shadowRef }) {
    const { dock, float, hideButton } = useActions(dockLogic)
    const { start, stop } = useActions(inspectElementLogic)
    const { selecting: inspectingElement } = useValues(inspectElementLogic)

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
        timeoutRef.current = window.setTimeout(() => setButtonsExtended(false), 1000)
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

    let index = 0
    const itemCount = 3
    const padding = -20
    const distance = buttonsExtended ? 100 : 0
    const closeDistance = buttonsExtended ? 50 : 0
    const inspectDistance = buttonsExtended ? distance : inspectingElement ? 50 : 0
    const heatmapDistance = buttonsExtended ? distance : 50 // TODO: reset to 0 when can be toggled

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
                    radius={48}
                    distance={inspectDistance}
                    rotate={getQuarterRotation({ itemCount, index: index++, padding, quarter: quarters[quarter] })}
                    content={
                        <Tooltip
                            title="Inspect Element"
                            placement={quarter.includes('e') ? 'right' : 'left'}
                            getPopupContainer={() => shadowRef.current.shadowRoot}
                        >
                            <SearchOutlined />
                        </Tooltip>
                    }
                    zIndex={1}
                    onMouseMove={onMouseMove}
                    onMouseLeave={onMouseLeave}
                    onClick={inspectingElement ? stop : start}
                    style={{
                        cursor: 'pointer',
                        background: inspectingElement ? 'rgb(84, 138, 248)' : 'hsla(220, 52%, 96%, 1)',
                        color: inspectingElement ? 'hsla(220, 52%, 96%, 1)' : 'rgb(84, 138, 248)',
                        fontSize: '32px',
                        transition: 'transform 0.2s, color 0.2s, background: 0.2s',
                        transform: `scale(${0.2 + (0.8 * inspectDistance) / 100})`,
                    }}
                />
                <Circle
                    radius={48}
                    distance={heatmapDistance}
                    rotate={getQuarterRotation({ itemCount, index: index++, padding, quarter: quarters[quarter] })}
                    content={
                        <Tooltip
                            title="Show Heatmap"
                            placement={quarter.includes('e') ? 'right' : 'left'}
                            getPopupContainer={() => shadowRef.current.shadowRoot}
                        >
                            <FireFilled />
                        </Tooltip>
                    }
                    zIndex={1}
                    onMouseMove={onMouseMove}
                    onMouseLeave={onMouseLeave}
                    onClick={float}
                    style={{
                        cursor: 'pointer',
                        background: '#FF5722',
                        color: '#FFEB3B',
                        fontSize: '32px',
                        transition: 'transform 0.2s',
                        transform: `scale(${0.2 + (0.8 * heatmapDistance) / 100})`,
                    }}
                />
                <Circle
                    radius={48}
                    distance={distance}
                    rotate={getQuarterRotation({ itemCount, index: index++, padding, quarter: quarters[quarter] })}
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
                    style={{
                        cursor: 'pointer',
                        fontSize: '24px',
                        transition: 'transform 0.2s',
                        transform: `scale(${0.2 + (0.8 * distance) / 100})`,
                    }}
                />

                <Circle
                    radius={32}
                    distance={closeDistance}
                    rotate={getQuarterRotation({ itemCount: 1, quarter: quarters[reverseQuarter(quarter)] })}
                    content={<CloseOutlined />}
                    zIndex={5}
                    onMouseMove={onMouseMove}
                    onMouseLeave={onMouseLeave}
                    onClick={hideButton}
                    style={{ cursor: 'pointer', background: 'rgba(255,255,255,0.5)' }}
                />
            </Circle>
        </>
    )
}
