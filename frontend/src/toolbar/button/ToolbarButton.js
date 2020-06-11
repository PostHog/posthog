import './ToolbarButton.scss'

import React, { useRef, useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { useLongPress } from 'lib/hooks/useLongPress'
import { CloseOutlined, ProfileOutlined, SearchOutlined, FireFilled } from '@ant-design/icons'
import { Tooltip } from 'antd'
import { Logo } from '~/toolbar/assets/Logo'
import { Circle } from '~/toolbar/button/Circle'
import { inspectElementLogic } from '~/toolbar/shared/inspectElementLogic'
import { toolbarButtonLogic } from '~/toolbar/button/toolbarButtonLogic'
import { heatmapLogic } from '~/toolbar/shared/heatmapLogic'

const quarters = { ne: 0, nw: 1, sw: 2, se: 3 }

function getQuarterRotation({ itemCount, index, quarter, padding: inputPadding }) {
    const padding = typeof inputPadding !== 'undefined' ? inputPadding : 90 / itemCount
    const angle = quarter * 90 + (itemCount === 1 ? 45 : padding / 2 + ((90 - padding) / (itemCount - 1)) * index)
    return -angle
}

function reverseQuarter(quarter) {
    return (quarter[0] === 'n' ? 's' : 'n') + (quarter[1] === 'e' ? 'w' : 'e')
}

export function ToolbarButton({ dockLogic, shadowRef }) {
    const { extensionPercentage, quarter } = useValues(toolbarButtonLogic)
    const { setExtensionPercentage, setQuarter } = useActions(toolbarButtonLogic)

    const { start, stop } = useActions(inspectElementLogic)
    const { selecting: inspectingElement } = useValues(inspectElementLogic)

    const { setHeatmapEnabled } = useActions(heatmapLogic)
    const { heatmapEnabled } = useValues(heatmapLogic)

    const { dock, float, hideButton } = useActions(dockLogic)

    function setQuarterFromShadowRef(shadowRef) {
        if (shadowRef.current) {
            const element = shadowRef.current.shadowRoot.getElementById('button-toolbar')
            if (element) {
                const rect = element.getBoundingClientRect()
                const x = rect.x + rect.width / 2
                const y = rect.y + rect.height / 2
                const ns = y < window.innerHeight / 2 ? 's' : 'n'
                const we = x < window.innerWidth / 2 ? 'e' : 'w'
                // use toolbarButtonLogic.values.quarter to always get the last state
                if (toolbarButtonLogic.values.quarter !== `${ns}${we}`) {
                    setQuarter(`${ns}${we}`)
                }
            }
        }
    }

    useEffect(() => {
        setQuarterFromShadowRef(shadowRef)
    }, [])

    const longPressEvents = useLongPress(
        clicked => {
            setQuarterFromShadowRef(shadowRef)

            if (clicked) {
                dock()
            } else {
                // extendButtons()
            }
        },
        { ms: 700, clickMs: 1 }
    )

    const globalMouseMove = useRef(null)
    useEffect(() => {
        globalMouseMove.current = function(e) {
            if (shadowRef.current) {
                setQuarterFromShadowRef(shadowRef)

                const element = shadowRef.current.shadowRoot.getElementById('button-toolbar')
                if (element) {
                    const rect = element.getBoundingClientRect()
                    const x = rect.left + rect.width / 2
                    const y = rect.top + rect.height / 2
                    const distance = Math.sqrt((e.clientX - x) * (e.clientX - x) + (e.clientY - y) * (e.clientY - y))

                    if (distance >= 230) {
                        if (toolbarButtonLogic.values.extensionPercentage !== 0) {
                            setExtensionPercentage(0)
                        }
                    } else if (distance >= 130 && distance < 230) {
                        setExtensionPercentage((230 - distance) / 100)
                    } else if (distance < 130) {
                        if (toolbarButtonLogic.values.extensionPercentage !== 1) {
                            setExtensionPercentage(1)
                        }
                    }
                }
            }
        }
        window.addEventListener('mousemove', globalMouseMove.current)
        return () => window.removeEventListener('mousemove', globalMouseMove.current)
    }, [shadowRef.current])

    let index = 0
    const itemCount = 3
    const padding = -20
    const distance = extensionPercentage * 100
    const closeDistance = extensionPercentage * 50
    const inspectDistance = inspectingElement
        ? Math.max(50, extensionPercentage * distance)
        : extensionPercentage * distance
    const heatmapDistance = heatmapEnabled
        ? Math.max(50, extensionPercentage * distance)
        : extensionPercentage * distance

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
                    onClick={() => setHeatmapEnabled(!heatmapEnabled)}
                    style={{
                        cursor: 'pointer',
                        background: heatmapEnabled ? '#FF5722' : 'hsl(14, 100%, 97%)',
                        color: heatmapEnabled ? '#FFEB3B' : '#FF5722',
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
                    onClick={hideButton}
                    style={{ cursor: 'pointer', background: 'black', color: 'white' }}
                />
            </Circle>
        </>
    )
}
