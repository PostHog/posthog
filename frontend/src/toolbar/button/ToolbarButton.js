import './ToolbarButton.scss'

import React, { useRef, useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { useLongPress } from 'lib/hooks/useLongPress'
import { Tooltip } from 'antd'
import { CloseOutlined, ProfileOutlined, SearchOutlined, FireFilled } from '@ant-design/icons'
import { Logo } from '~/toolbar/assets/Logo'
import { Circle } from '~/toolbar/button/Circle'
import { toolbarButtonLogic } from '~/toolbar/button/toolbarButtonLogic'
import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'
import { dockLogic } from '~/toolbar/dockLogic'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { getShadowRoot } from '~/toolbar/elements/utils'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { heatmapLabelStyle } from '~/toolbar/elements/HeatmapLabel'

const quarters = { ne: 0, nw: 1, sw: 2, se: 3 }

function getQuarterRotation({ itemCount, index, quarter, padding: inputPadding }) {
    const padding = typeof inputPadding !== 'undefined' ? inputPadding : 90 / itemCount
    const angle = quarter * 90 + (itemCount === 1 ? 45 : padding / 2 + ((90 - padding) / (itemCount - 1)) * index)
    return -angle
}

export function ToolbarButton() {
    const { extensionPercentage, quarter } = useValues(toolbarButtonLogic)
    const { setExtensionPercentage, setQuarter } = useActions(toolbarButtonLogic)

    const { enableInspect, disableInspect } = useActions(elementsLogic)
    const { inspectEnabled, selectedElement } = useValues(elementsLogic)

    const { enableHeatmap, disableHeatmap } = useActions(heatmapLogic)
    const { heatmapEnabled, heatmapLoading, elementCount, clickCount } = useValues(heatmapLogic)

    const { dock, float, hideButton } = useActions(dockLogic)

    const { isAuthenticated } = useValues(toolbarLogic)
    const { authenticate } = useActions(toolbarLogic)

    function updateQuarter(buttonDiv = getShadowRoot()?.getElementById('button-toolbar')) {
        if (buttonDiv) {
            const rect = buttonDiv.getBoundingClientRect()
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

    useEffect(() => updateQuarter(), [])

    const longPressEvents = useLongPress(
        clicked => {
            updateQuarter()
            if (isAuthenticated) {
                if (clicked) {
                    dock()
                } else {
                    setExtensionPercentage(1)
                }
            } else {
                authenticate()
            }
        },
        { ms: 700, clickMs: 1 }
    )

    const globalMouseMove = useRef(null)
    useEffect(() => {
        globalMouseMove.current = function(e) {
            const buttonDiv = getShadowRoot()?.getElementById('button-toolbar')
            if (buttonDiv) {
                updateQuarter(buttonDiv)
                const rect = buttonDiv.getBoundingClientRect()
                const x = rect.left + rect.width / 2
                const y = rect.top + rect.height / 2
                const distance = Math.sqrt((e.clientX - x) * (e.clientX - x) + (e.clientY - y) * (e.clientY - y))

                const startDistance = isAuthenticated ? 230 : 130
                const endDistance = isAuthenticated ? 160 : 60

                if (distance >= startDistance) {
                    if (toolbarButtonLogic.values.extensionPercentage !== 0) {
                        setExtensionPercentage(0)
                    }
                } else if (distance >= endDistance && distance < startDistance) {
                    setExtensionPercentage((startDistance - distance) / (startDistance - endDistance))
                } else if (distance < endDistance) {
                    if (toolbarButtonLogic.values.extensionPercentage !== 1) {
                        setExtensionPercentage(1)
                    }
                }
            }
        }
        window.addEventListener('mousemove', globalMouseMove.current)
        return () => window.removeEventListener('mousemove', globalMouseMove.current)
    }, [isAuthenticated])

    let index = 0
    const itemCount = 3
    const padding = -20
    const distance = extensionPercentage * 100
    const closeDistance = extensionPercentage * 50
    const inspectDistance = inspectEnabled ? Math.max(50, distance) : distance
    const heatmapDistance = heatmapEnabled ? Math.max(50, distance) : distance

    return (
        <Circle
            rootNode
            width={64}
            className="floating-toolbar-button"
            content={<Logo style={{ width: 54, height: 54, filter: 'invert(1)', cursor: 'pointer' }} />}
            label={
                isAuthenticated ? (
                    'Toolbar'
                ) : (
                    <div style={{ lineHeight: '22px', paddingTop: 5 }}>
                        Click here to
                        <br />
                        authenticate
                    </div>
                )
            }
            labelStyle={{ opacity: extensionPercentage > 0.8 ? (extensionPercentage - 0.8) / 0.2 : 0 }}
            {...longPressEvents}
            zIndex={3}
        >
            <Circle
                width={32}
                distance={closeDistance}
                rotate={quarter === 'sw' || quarter === 'nw' ? -45 : -135}
                content={<CloseOutlined />}
                zIndex={5}
                onClick={hideButton}
                style={{ cursor: 'pointer', background: 'black', color: 'white' }}
            />
            {isAuthenticated ? (
                <>
                    <Circle
                        width={48}
                        distance={inspectDistance}
                        rotate={getQuarterRotation({
                            itemCount,
                            index: index++,
                            padding,
                            quarter: quarters[quarter],
                        })}
                        label="Inspect"
                        labelStyle={{ opacity: inspectDistance > 80 ? (inspectDistance - 80) / 20 : 0 }}
                        content={
                            <div style={{ position: 'relative' }}>
                                <SearchOutlined />
                                {inspectEnabled && selectedElement ? (
                                    <div
                                        style={{
                                            position: 'absolute',
                                            top: 12,
                                            left: 6,
                                            fontSize: 13,
                                            color: 'white',
                                        }}
                                    >
                                        <CloseOutlined />
                                    </div>
                                ) : null}
                            </div>
                        }
                        zIndex={1}
                        onClick={inspectEnabled ? disableInspect : enableInspect}
                        style={{
                            cursor: 'pointer',
                            background: inspectEnabled ? 'rgb(84, 138, 248)' : 'hsla(220, 52%, 96%, 1)',
                            color: inspectEnabled ? 'hsla(220, 52%, 96%, 1)' : 'rgb(84, 138, 248)',
                            fontSize: '32px',
                            transition: 'transform 0.2s, color 0.2s, background: 0.2s',
                            transform: `scale(${0.2 + (0.8 * inspectDistance) / 100})`,
                        }}
                    />
                    <Circle
                        width={48}
                        distance={heatmapDistance}
                        rotate={getQuarterRotation({
                            itemCount,
                            index: index++,
                            padding,
                            quarter: quarters[quarter],
                        })}
                        label="Heatmap"
                        labelStyle={{ opacity: heatmapDistance > 80 ? (heatmapDistance - 80) / 20 : 0 }}
                        content={<FireFilled />}
                        zIndex={1}
                        onClick={heatmapEnabled ? disableHeatmap : enableHeatmap}
                        style={{
                            cursor: 'pointer',
                            background: heatmapEnabled ? '#FF5722' : 'hsl(14, 100%, 97%)',
                            color: heatmapEnabled ? '#FFEB3B' : '#FF5722',
                            fontSize: '32px',
                            transition: 'transform 0.2s',
                            transform: `scale(${0.2 + (0.8 * heatmapDistance) / 100})`,
                        }}
                    >
                        {heatmapLoading ? (
                            <Circle
                                width={12}
                                distance={30 * (0.2 + (0.8 * heatmapDistance) / 100)}
                                rotate={0}
                                animate
                                animationId="heatmap-loading"
                                animationDuration={0.5 + (0.5 * heatmapDistance) / 100}
                                spin="1s linear infinite"
                                content={<FireFilled />}
                                zIndex={3}
                                style={{
                                    cursor: 'pointer',
                                    background: '#FF5722',
                                    color: '#FFEB3B',
                                    fontSize: '12px',
                                    transition: 'transform 0.2s',
                                    transform: `rotate(${-getQuarterRotation({
                                        itemCount,
                                        index: index - 1,
                                        padding,
                                        quarter: quarters[quarter],
                                    })}deg)`,
                                }}
                            />
                        ) : heatmapEnabled ? (
                            <Circle
                                width={16}
                                distance={30 * (0.1 + (0.8 * heatmapDistance) / 100)}
                                rotate={
                                    -getQuarterRotation({
                                        itemCount,
                                        index: index - 1,
                                        padding,
                                        quarter: quarters[quarter],
                                    }) - (quarter === 'sw' || quarter === 'nw' ? 135 : 45)
                                }
                                content={
                                    <Tooltip
                                        getPopupContainer={getShadowRoot}
                                        title={
                                            elementCount === 0 ? (
                                                'No clicks were recorded on this page in the last 7 days'
                                            ) : (
                                                <>
                                                    <div style={{ marginBottom: 10 }}>
                                                        {'Recorded '}
                                                        <strong>
                                                            {elementCount} element{elementCount === 1 ? '' : 's'}
                                                        </strong>
                                                        {' with '}
                                                        <strong>
                                                            {clickCount} click{clickCount === 1 ? '' : 's'}
                                                        </strong>
                                                        {' in the last  '}
                                                        <u>7 days</u>.
                                                    </div>
                                                    <div>
                                                        {'Look for elements with yellow labels: '}
                                                        <span style={heatmapLabelStyle}>1</span>
                                                        {', '}
                                                        <span style={heatmapLabelStyle}>2</span>
                                                        {', '}
                                                        <span style={heatmapLabelStyle}>3</span>
                                                        {' and so on.'}
                                                    </div>
                                                </>
                                            )
                                        }
                                    >
                                        <div style={{ whiteSpace: 'nowrap', minWidth: 16, textAlign: 'center' }}>
                                            {elementCount}
                                        </div>
                                    </Tooltip>
                                }
                                zIndex={4}
                                style={{
                                    cursor: 'pointer',
                                    background: 'hsla(14, 92%, 23%, 1)',
                                    color: 'white',
                                    fontSize: '12px',
                                    transition: 'transform 0.2s',
                                    transform: `rotate(${-getQuarterRotation({
                                        itemCount,
                                        index: index - 1,
                                        padding,
                                        quarter: quarters[quarter],
                                    })}deg)`,
                                    width: 'auto',
                                    minWidth: 16,
                                }}
                            />
                        ) : null}
                    </Circle>
                    <Circle
                        width={48}
                        distance={distance}
                        rotate={getQuarterRotation({
                            itemCount,
                            index: index++,
                            padding,
                            quarter: quarters[quarter],
                        })}
                        label="Float"
                        labelStyle={{ opacity: distance > 80 ? (distance - 80) / 20 : 0 }}
                        content={<ProfileOutlined style={{ color: '#333' }} />}
                        zIndex={1}
                        onClick={float}
                        style={{
                            cursor: 'pointer',
                            fontSize: '24px',
                            transition: 'transform 0.2s',
                            transform: `scale(${0.2 + (0.8 * distance) / 100})`,
                        }}
                    />
                </>
            ) : null}
        </Circle>
    )
}
