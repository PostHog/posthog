import './ToolbarButton.scss'

import React, { useRef, useEffect } from 'react'
import { useActions, useValues } from 'kea'
import {
    CloseOutlined,
    FlagOutlined,
    SearchOutlined,
    FireFilled,
    DatabaseOutlined,
    LineChartOutlined,
} from '@ant-design/icons'
import { HogLogo } from '~/toolbar/assets/HogLogo'
import { Circle } from '~/toolbar/button/Circle'
import { toolbarButtonLogic } from '~/toolbar/button/toolbarButtonLogic'
import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'
import { dockLogic } from '~/toolbar/dockLogic'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { getShadowRoot } from '~/toolbar/utils'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { useLongPress } from 'lib/hooks/useLongPress'

export function ToolbarButton() {
    const { extensionPercentage, heatmapInfoVisible, toolbarListVerticalPadding, dockButtonOnTop, side } = useValues(
        toolbarButtonLogic
    )
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
                distance={58}
                rotation={-54}
                content={<CloseOutlined />}
                zIndex={5}
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
                        zIndex={5}
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
                        y={-90 + toolbarListVerticalPadding}
                        extensionPercentage={extensionPercentage}
                        rotationFixer={r => (side === 'right' && r < 0 ? 360 : 0)}
                        label="Inspect"
                        labelPosition={side === 'left' ? 'right' : 'left'}
                        labelStyle={{ opacity: extensionPercentage > 0.8 ? (extensionPercentage - 0.8) / 0.2 : 0 }}
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
                            transform: `scale(${0.2 + 0.8 * extensionPercentage})`,
                            borderRadius,
                        }}
                    />
                    <Circle
                        width={buttonWidth}
                        x={side === 'left' ? 80 : -80}
                        y={-30 + toolbarListVerticalPadding}
                        extensionPercentage={extensionPercentage}
                        rotationFixer={r => (side === 'right' && r < 0 ? 360 : 0)}
                        label={heatmapEnabled && !heatmapLoading ? null : 'Heatmap'}
                        labelPosition={side === 'left' ? 'right' : 'left'}
                        labelStyle={{
                            opacity:
                                heatmapEnabled && !heatmapLoading
                                    ? 0
                                    : extensionPercentage > 0.8
                                    ? (extensionPercentage - 0.8) / 0.2
                                    : 0,
                        }}
                        content={<FireFilled />}
                        zIndex={2}
                        onClick={heatmapEnabled ? disableHeatmap : enableHeatmap}
                        style={{
                            cursor: 'pointer',
                            background: heatmapEnabled ? '#FF5722' : 'hsl(14, 100%, 97%)',
                            color: heatmapEnabled ? '#FFEB3B' : '#FF5722',
                            fontSize: '32px',
                            transform: `scale(${0.2 + 0.8 * extensionPercentage})`,
                            borderRadius,
                        }}
                    >
                        {heatmapLoading ? (
                            <Circle
                                width={12}
                                distance={30 * (0.2 + 0.8 * extensionPercentage)}
                                rotation={0}
                                animate
                                animationId="heatmap-loading"
                                animationDuration={0.5 + 0.5 * extensionPercentage}
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
                                x={-50}
                                y={0}
                                content={
                                    <div style={{ whiteSpace: 'nowrap', textAlign: 'center' }}>{elementCount}</div>
                                }
                                label="Stats"
                                labelPosition="left"
                                zIndex={4}
                                onClick={heatmapInfoVisible ? hideHeatmapInfo : showHeatmapInfo}
                                style={{
                                    cursor: 'pointer',
                                    background: heatmapInfoVisible ? '#FF5722' : 'hsl(14, 100%, 97%)',
                                    color: heatmapInfoVisible ? '#FFEB3B' : '#FF5722',
                                    fontSize: '20px',
                                    transform: `scale(${0.2 + 0.8 * extensionPercentage})`,
                                    borderRadius,
                                }}
                            />
                        ) : null}
                    </Circle>
                    <Circle
                        width={buttonWidth}
                        x={side === 'left' ? 80 : -80}
                        y={30 + toolbarListVerticalPadding}
                        extensionPercentage={extensionPercentage}
                        rotationFixer={r => (side === 'right' && r < 0 ? 360 : 0)}
                        label="Actions"
                        labelPosition={side === 'left' ? 'right' : 'left'}
                        labelStyle={{ opacity: extensionPercentage > 0.8 ? (extensionPercentage - 0.8) / 0.2 : 0 }}
                        content={<FlagOutlined />}
                        zIndex={1}
                        onClick={dock}
                        style={{
                            cursor: 'pointer',
                            fontSize: '24px',
                            transform: `scale(${0.2 + 0.8 * extensionPercentage})`,
                            color: 'hsl(111, 42%, 41%)',
                            background: 'hsla(111, 42%, 95%, 1)',
                            borderRadius,
                        }}
                    />
                    <Circle
                        width={buttonWidth}
                        x={side === 'left' ? 80 : -80}
                        y={90 + toolbarListVerticalPadding}
                        extensionPercentage={extensionPercentage}
                        rotationFixer={r => (side === 'right' && r < 0 ? 360 : 0)}
                        label="Stats"
                        labelPosition={side === 'left' ? 'right' : 'left'}
                        labelStyle={{ opacity: extensionPercentage > 0.8 ? (extensionPercentage - 0.8) / 0.2 : 0 }}
                        content={<LineChartOutlined />}
                        zIndex={1}
                        onClick={dock}
                        style={{
                            cursor: 'pointer',
                            fontSize: '24px',
                            transform: `scale(${0.2 + 0.8 * extensionPercentage})`,
                            background: 'hsla(42, 95%, 93%, 1)',
                            color: 'hsla(42, 95%, 38%, 1)',
                            borderRadius,
                        }}
                    />
                </>
            ) : null}
        </Circle>
    )
}
