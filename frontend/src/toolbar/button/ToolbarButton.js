import './ToolbarButton.scss'

import React, { useRef, useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { useLongPress } from 'lib/hooks/useLongPress'
import { CloseOutlined, ProfileOutlined, SearchOutlined, FireFilled } from '@ant-design/icons'
import { Logo } from '~/toolbar/assets/Logo'
import { Circle } from '~/toolbar/button/Circle'
import { inspectElementLogic } from '~/toolbar/shared/inspectElementLogic'
import { toolbarButtonLogic } from '~/toolbar/button/toolbarButtonLogic'
import { heatmapLogic } from '~/toolbar/shared/heatmapLogic'
import { dockLogic } from '~/toolbar/dockLogic'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { getShadowRoot } from '~/toolbar/shared/utils'
import { ChangingText } from '~/toolbar/button/ChangingText'

const quarters = { ne: 0, nw: 1, sw: 2, se: 3 }

function getQuarterRotation({ itemCount, index, quarter, padding: inputPadding }) {
    const padding = typeof inputPadding !== 'undefined' ? inputPadding : 90 / itemCount
    const angle = quarter * 90 + (itemCount === 1 ? 45 : padding / 2 + ((90 - padding) / (itemCount - 1)) * index)
    return -angle
}

function reverseQuarter(quarter) {
    return (quarter[0] === 'n' ? 's' : 'n') + (quarter[1] === 'e' ? 'w' : 'e')
}

const hedgehogWalk = () => Array.from(Array(10)).map((_, i) => [`${'_'.repeat(10 - i)}🦔${'_'.repeat(i)}`, 60])

const loggedOutLines = hedgehogWalk().concat([
    ['Click', 300],
    ['here', 250],
    ['to', 200],
    ['start', 200],
    ['using', 200],
    ['the', 200],
    ['PostHog', 350],
    ['Toolbar!', 2500],
])

export function ToolbarButton() {
    const { extensionPercentage, quarter } = useValues(toolbarButtonLogic)
    const { setExtensionPercentage, setQuarter } = useActions(toolbarButtonLogic)

    const { start, stop } = useActions(inspectElementLogic)
    const { selecting: inspectingElement, selectedElement: selectedInspectElement } = useValues(inspectElementLogic)

    const { setHeatmapEnabled } = useActions(heatmapLogic)
    const { heatmapEnabled, heatmapLoading } = useValues(heatmapLogic)

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
                    // extendButtons()
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
    const inspectDistance = inspectingElement || selectedInspectElement ? Math.max(50, distance) : distance
    const heatmapDistance = heatmapEnabled ? Math.max(50, distance) : distance

    return (
        <Circle
            rootNode
            width={64}
            className="floating-toolbar-button"
            content={<Logo style={{ width: 54, height: 54, filter: 'invert(1)', cursor: 'pointer' }} />}
            label={
                isAuthenticated ? 'Toolbar' : extensionPercentage > 0.8 ? <ChangingText lines={loggedOutLines} /> : null
            }
            labelStyle={{ opacity: extensionPercentage > 0.8 ? (extensionPercentage - 0.8) / 0.2 : 0 }}
            {...longPressEvents}
            zIndex={3}
        >
            <Circle
                width={32}
                distance={closeDistance}
                rotate={getQuarterRotation({ itemCount: 1, quarter: quarters[reverseQuarter(quarter)] })}
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
                                {selectedInspectElement ? (
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
                        onClick={inspectingElement || selectedInspectElement ? stop : start}
                        style={{
                            cursor: 'pointer',
                            background:
                                inspectingElement || selectedInspectElement
                                    ? 'rgb(84, 138, 248)'
                                    : 'hsla(220, 52%, 96%, 1)',
                            color:
                                inspectingElement || selectedInspectElement
                                    ? 'hsla(220, 52%, 96%, 1)'
                                    : 'rgb(84, 138, 248)',
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
                        onClick={() => setHeatmapEnabled(!heatmapEnabled)}
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
                        content={<ProfileOutlined />}
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
