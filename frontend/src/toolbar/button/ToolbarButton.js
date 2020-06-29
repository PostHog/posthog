import './ToolbarButton.scss'

import React, { useRef, useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { CloseOutlined, FireFilled, DatabaseOutlined } from '@ant-design/icons'
import { HogLogo } from '~/toolbar/assets/HogLogo'
import { Circle } from '~/toolbar/button/Circle'
import { toolbarButtonLogic } from '~/toolbar/button/toolbarButtonLogic'
import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'
import { dockLogic } from '~/toolbar/dockLogic'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { getShadowRoot } from '~/toolbar/utils'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { useLongPress } from 'lib/hooks/useLongPress'
import { Stats } from '~/toolbar/button/icons/Stats'
import { Flag } from '~/toolbar/button/icons/Flag'
import { Fire } from '~/toolbar/button/icons/Fire'
import { Magnifier } from '~/toolbar/button/icons/Magnifier'

export function ToolbarButton() {
    const {
        extensionPercentage,
        heatmapInfoVisible,
        toolbarListVerticalPadding,
        dockButtonOnTop,
        side,
        closeDistance,
        closeRotation,
        inspectExtensionPercentage,
        heatmapExtensionPercentage,
        heatmapButtonPosition,
        heatmapButtonIndependent,
    } = useValues(toolbarButtonLogic)

    const { setExtensionPercentage, showHeatmapInfo, hideHeatmapInfo } = useActions(toolbarButtonLogic)

    const { enableInspect, disableInspect } = useActions(elementsLogic)
    const { inspectEnabled, selectedElement } = useValues(elementsLogic)

    const { enableHeatmap, disableHeatmap } = useActions(heatmapLogic)
    const { heatmapEnabled, heatmapLoading, elementCount } = useValues(heatmapLogic)

    const { dock, hideButton } = useActions(dockLogic)

    const { isAuthenticated } = useValues(toolbarLogic)
    const { authenticate } = useActions(toolbarLogic)

    const globalMouseMove = useRef(null)
    useEffect(() => {
        globalMouseMove.current = function(e) {
            const buttonDiv = getShadowRoot()?.getElementById('button-toolbar')
            if (buttonDiv) {
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

    // using useLongPress for short presses (clicks) since it detects if the element was dragged (no click) or not (click)
    const clickEvents = useLongPress(
        clicked => {
            if (clicked) {
                if (isAuthenticated) {
                    setExtensionPercentage(extensionPercentage === 1 ? 0 : 1)
                } else {
                    authenticate()
                }
            }
        },
        {
            ms: null,
            clickMs: 1,
            touch: true,
            click: true,
        }
    )

    const borderRadius = 14
    const buttonWidth = 42
    let n = 0

    return (
        <Circle
            rootNode
            width={62}
            className="floating-toolbar-button"
            content={<HogLogo style={{ width: 45, cursor: 'pointer' }} />}
            label={
                isAuthenticated ? null : (
                    <div style={{ lineHeight: '22px', paddingTop: 5 }}>
                        Click here to
                        <br />
                        authenticate
                    </div>
                )
            }
            labelStyle={{ opacity: extensionPercentage > 0.8 ? (extensionPercentage - 0.8) / 0.2 : 0, marginTop: 16 }}
            {...clickEvents}
            style={{ borderRadius: 10, height: 46, marginTop: -23 }}
            zIndex={3}
        >
            <Circle
                width={26}
                extensionPercentage={extensionPercentage}
                distance={closeDistance}
                rotation={closeRotation}
                content={<CloseOutlined />}
                zIndex={extensionPercentage > 0.95 ? 5 : 2}
                onClick={hideButton}
                style={{ cursor: 'pointer', background: 'black', color: 'white' }}
            />
            {isAuthenticated ? (
                <>
                    <Circle
                        width={32}
                        extensionPercentage={extensionPercentage}
                        distance={dockButtonOnTop ? 90 : 55}
                        rotation={dockButtonOnTop ? (side === 'left' ? -95 + 360 : -95) : 90}
                        content={<DatabaseOutlined />}
                        label="Dock"
                        zIndex={2}
                        onClick={dock}
                        labelStyle={{ opacity: extensionPercentage > 0.8 ? (extensionPercentage - 0.8) / 0.2 : 0 }}
                        style={{
                            cursor: 'pointer',
                            background: 'hsla(228, 29%, 26%, 1)',
                            color: 'white',
                            borderRadius: 8,
                        }}
                    />
                    <Circle
                        width={buttonWidth}
                        x={side === 'left' ? 80 : -80}
                        y={toolbarListVerticalPadding + n++ * 60}
                        extensionPercentage={inspectExtensionPercentage}
                        rotationFixer={r => (side === 'right' && r < 0 ? 360 : 0)}
                        label="Inspect"
                        labelPosition={side === 'left' ? 'right' : 'left'}
                        labelStyle={{
                            opacity: inspectExtensionPercentage > 0.8 ? (inspectExtensionPercentage - 0.8) / 0.2 : 0,
                        }}
                        content={
                            <div style={{ position: 'relative' }}>
                                <Magnifier style={{ height: 34, paddingTop: 2 }} engaged={inspectEnabled} />
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
                            background: inspectEnabled ? '#8F98FF' : '#E7EAFD',
                            transition: 'transform 0.2s, color 0.2s, background: 0.2s',
                            transform: `scale(${0.2 + 0.8 * inspectExtensionPercentage})`,
                            borderRadius,
                        }}
                    />
                    <Circle
                        width={buttonWidth}
                        x={side === 'left' ? 80 : -80}
                        y={toolbarListVerticalPadding + n++ * 60}
                        extensionPercentage={heatmapExtensionPercentage}
                        rotationFixer={r => (side === 'right' && r < 0 ? 360 : 0)}
                        label={heatmapEnabled && !heatmapLoading ? null : 'Heatmap'}
                        labelPosition={side === 'left' ? 'right' : 'left'}
                        labelStyle={{
                            opacity:
                                heatmapEnabled && !heatmapLoading
                                    ? 0
                                    : heatmapExtensionPercentage > 0.8
                                    ? (heatmapExtensionPercentage - 0.8) / 0.2
                                    : 0,
                        }}
                        content={<Fire style={{ height: 26 }} engaged={heatmapEnabled} />}
                        zIndex={2}
                        onClick={heatmapEnabled ? disableHeatmap : enableHeatmap}
                        style={{
                            cursor: 'pointer',
                            background: heatmapEnabled ? '#FF9870' : '#FEE3DA',
                            transform: `scale(${0.2 + 0.8 * heatmapExtensionPercentage})`,
                            borderRadius,
                        }}
                    >
                        {heatmapLoading ? (
                            <Circle
                                width={12}
                                distance={30 * (0.2 + 0.8 * heatmapExtensionPercentage)}
                                rotation={0}
                                animate
                                animationId="heatmap-loading"
                                animationDuration={0.5 + 0.5 * heatmapExtensionPercentage}
                                spin="1s linear infinite"
                                content={<FireFilled />}
                                zIndex={3}
                                style={{
                                    cursor: 'pointer',
                                    background: '#FF5722',
                                    color: '#FFEB3B',
                                    fontSize: '12px',
                                    transition: 'transform 0.2s',
                                }}
                            />
                        ) : heatmapEnabled ? (
                            <Circle
                                width={26}
                                x={heatmapButtonPosition.x}
                                y={heatmapButtonPosition.y}
                                content={
                                    <div style={{ whiteSpace: 'nowrap', textAlign: 'center' }}>
                                        {heatmapButtonIndependent ? 'X' : elementCount}
                                    </div>
                                }
                                labelPosition={side === 'left' ? 'right' : 'left'}
                                zIndex={4}
                                onClick={heatmapInfoVisible ? hideHeatmapInfo : showHeatmapInfo}
                                style={{
                                    cursor: 'pointer',
                                    background: heatmapInfoVisible ? '#FF5722' : 'hsl(14, 100%, 97%)',
                                    color: heatmapInfoVisible ? '#FFEB3B' : '#FF5722',
                                    width: 'auto',
                                    minWidth: 26,
                                    fontSize: '20px',
                                    lineHeight: '26px',
                                    padding: '0 4px',
                                    transform: `scale(${0.2 + 0.8 * heatmapExtensionPercentage})`,
                                    borderRadius: 7,
                                }}
                            />
                        ) : null}
                    </Circle>
                    <Circle
                        width={buttonWidth}
                        x={side === 'left' ? 80 : -80}
                        y={toolbarListVerticalPadding + n++ * 60}
                        extensionPercentage={extensionPercentage}
                        rotationFixer={r => (side === 'right' && r < 0 ? 360 : 0)}
                        label="Actions"
                        labelPosition={side === 'left' ? 'right' : 'left'}
                        labelStyle={{ opacity: extensionPercentage > 0.8 ? (extensionPercentage - 0.8) / 0.2 : 0 }}
                        content={<Flag style={{ height: 30 }} />}
                        zIndex={1}
                        onClick={dock}
                        style={{
                            cursor: 'pointer',
                            transform: `scale(${0.2 + 0.8 * extensionPercentage})`,
                            background: '#D6EBCC', // engaged: #94D674
                            borderRadius,
                        }}
                    />
                    <Circle
                        width={buttonWidth}
                        x={side === 'left' ? 80 : -80}
                        y={toolbarListVerticalPadding + n++ * 60}
                        extensionPercentage={extensionPercentage}
                        rotationFixer={r => (side === 'right' && r < 0 ? 360 : 0)}
                        label="Stats"
                        labelPosition={side === 'left' ? 'right' : 'left'}
                        labelStyle={{ opacity: extensionPercentage > 0.8 ? (extensionPercentage - 0.8) / 0.2 : 0 }}
                        content={<Stats style={{ height: 23 }} />}
                        zIndex={1}
                        onClick={dock}
                        style={{
                            cursor: 'pointer',
                            transform: `scale(${0.2 + 0.8 * extensionPercentage})`,
                            background: '#FFE19B', // engaged: #FFCB51
                            borderRadius,
                        }}
                    />
                </>
            ) : null}
        </Circle>
    )
}
