import './ToolbarButton.scss'

import React, { useRef, useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { HogLogo } from '~/toolbar/assets/HogLogo'
import { Circle } from '~/toolbar/button/Circle'
import { toolbarButtonLogic } from '~/toolbar/button/toolbarButtonLogic'
import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { getShadowRoot, getShadowRootPopupContainer } from '~/toolbar/utils'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { useLongPress } from 'lib/hooks/useLongPress'
import { Flag } from '~/toolbar/button/icons/Flag'
import { Fire } from '~/toolbar/button/icons/Fire'
import { Magnifier } from '~/toolbar/button/icons/Magnifier'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { actionsLogic } from '~/toolbar/actions/actionsLogic'
import { Close } from '~/toolbar/button/icons/Close'
import { AimOutlined, QuestionOutlined } from '@ant-design/icons'
import { Tooltip } from 'lib/components/Tooltip'
import { FEATURE_FLAGS } from 'lib/constants'

const HELP_URL =
    'https://posthog.com/docs/tutorials/toolbar?utm_medium=in-product&utm_source=in-product&utm_campaign=toolbar-help-button'

export function ToolbarButton(): JSX.Element {
    const {
        extensionPercentage,
        heatmapInfoVisible,
        toolbarListVerticalPadding,
        helpButtonOnTop,
        side,
        closeDistance,
        closeRotation,
        inspectExtensionPercentage,
        heatmapExtensionPercentage,
        actionsExtensionPercentage,
        actionsInfoVisible,
        featureFlagsExtensionPercentage,
        flagsVisible,
    } = useValues(toolbarButtonLogic)
    const {
        setExtensionPercentage,
        showHeatmapInfo,
        hideHeatmapInfo,
        showActionsInfo,
        hideActionsInfo,
        showFlags,
        hideFlags,
    } = useActions(toolbarButtonLogic)
    const { buttonActionsVisible, showActionsTooltip } = useValues(actionsTabLogic)
    const { hideButtonActions, showButtonActions } = useActions(actionsTabLogic)
    const { actionCount, allActionsLoading } = useValues(actionsLogic)

    const { enableInspect, disableInspect } = useActions(elementsLogic)
    const { inspectEnabled, selectedElement } = useValues(elementsLogic)

    const { enableHeatmap, disableHeatmap } = useActions(heatmapLogic)
    const { heatmapEnabled, heatmapLoading, elementCount, showHeatmapTooltip } = useValues(heatmapLogic)

    const { isAuthenticated, featureFlags } = useValues(toolbarLogic)
    const { authenticate, logout } = useActions(toolbarLogic)

    const globalMouseMove = useRef((e: MouseEvent) => {
        e
    })

    // Tricky: the feature flag's used here are not PostHog's normal feature flags, rather they're
    // the feature flags of the user. The toolbar does not have access to posthog's feature flags because
    // it uses Posthog-js-lite. As a result, this feature flag can only be turned on for posthog internal
    // (or any other posthog customer that has a flag with the name `posthog-toolbar-feature-flags` set).
    // (Should be removed when we want to roll this out broadly)
    const showFeatureFlags = featureFlags[FEATURE_FLAGS.TOOLBAR_FEATURE_FLAGS]

    useEffect(
        () => {
            globalMouseMove.current = function (e: MouseEvent): void {
                const buttonDiv = getShadowRoot()?.getElementById('button-toolbar')
                if (buttonDiv) {
                    const rect = buttonDiv.getBoundingClientRect()
                    const x = rect.left + rect.width / 2
                    const y = rect.top + rect.height / 2
                    const distance = Math.sqrt((e.clientX - x) * (e.clientX - x) + (e.clientY - y) * (e.clientY - y))

                    const maxDistance = isAuthenticated ? 300 : 100

                    if (distance >= maxDistance && toolbarButtonLogic.values.extensionPercentage !== 0) {
                        setExtensionPercentage(0)
                    }
                }
            }
            window.addEventListener('mousemove', globalMouseMove.current)
            return () => window.removeEventListener('mousemove', globalMouseMove.current)
        },
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [isAuthenticated]
    )

    // using useLongPress for short presses (clicks) since it detects if the element was dragged (no click) or not (click)
    const clickEvents = useLongPress(
        (clicked) => {
            if (clicked) {
                if (isAuthenticated) {
                    setExtensionPercentage(extensionPercentage === 1 ? 0 : 1)
                } else {
                    authenticate()
                }
            }
        },
        {
            ms: undefined,
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
            {...clickEvents}
            onMouseOver={isAuthenticated ? undefined : () => setExtensionPercentage(1)}
            style={{ borderRadius: 10, height: 46, marginTop: -23 }}
            zIndex={3}
        >
            <Circle
                width={26}
                extensionPercentage={extensionPercentage}
                distance={closeDistance}
                rotation={closeRotation}
                content={<Close style={{ width: 14, height: 14 }} />}
                zIndex={extensionPercentage > 0.95 ? 5 : 2}
                onClick={logout}
                style={{
                    cursor: 'pointer',
                    background: '#393939',
                    borderRadius: 6,
                    color: 'white',
                    transform: `scale(${0.2 + 0.8 * extensionPercentage})`,
                }}
            />
            {isAuthenticated ? (
                <>
                    <Circle
                        width={32}
                        extensionPercentage={extensionPercentage}
                        distance={helpButtonOnTop ? 75 : 55}
                        rotation={helpButtonOnTop ? (side === 'left' ? -95 + 360 : -95) : 90}
                        content={<QuestionOutlined style={{ fontSize: 22 }} />}
                        label="Help"
                        zIndex={2}
                        onClick={() => window.open(HELP_URL, '_blank')?.focus()}
                        labelStyle={{ opacity: extensionPercentage > 0.8 ? (extensionPercentage - 0.8) / 0.2 : 0 }}
                        style={{
                            cursor: 'pointer',
                            background: '#777',
                            color: 'white',
                            borderRadius: 10,
                            transform: `scale(${0.2 + 0.8 * extensionPercentage})`,
                        }}
                    />
                    <Circle
                        width={buttonWidth}
                        x={side === 'left' ? 80 : -80}
                        y={toolbarListVerticalPadding + n++ * 60}
                        extensionPercentage={inspectExtensionPercentage}
                        rotationFixer={(r) => (side === 'right' && r < 0 ? 360 : 0)}
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
                                            top: 8,
                                            left: 9,
                                            fontSize: 13,
                                            color: 'white',
                                        }}
                                    >
                                        <Close style={{ width: 10, height: 10 }} />
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
                        rotationFixer={(r) => (side === 'right' && r < 0 ? 360 : 0)}
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
                        content={<Fire style={{ height: 26 }} engaged={heatmapEnabled} animated={heatmapLoading} />}
                        zIndex={2}
                        onClick={heatmapEnabled ? disableHeatmap : enableHeatmap}
                        style={{
                            cursor: 'pointer',
                            background: heatmapEnabled ? '#FF9870' : '#FEE3DA',
                            transform: `scale(${0.2 + 0.8 * heatmapExtensionPercentage})`,
                            borderRadius,
                        }}
                    >
                        {heatmapEnabled && !heatmapLoading ? (
                            <Circle
                                width={26}
                                x={
                                    (side === 'left' ? 50 : -50) *
                                    heatmapExtensionPercentage *
                                    heatmapExtensionPercentage
                                }
                                y={0}
                                content={
                                    <Tooltip
                                        visible={showHeatmapTooltip}
                                        title="Click for details"
                                        placement={side === 'left' ? 'right' : 'left'}
                                        getPopupContainer={getShadowRootPopupContainer}
                                    >
                                        <div style={{ whiteSpace: 'nowrap', textAlign: 'center' }}>{elementCount}</div>
                                    </Tooltip>
                                }
                                zIndex={4}
                                onClick={heatmapInfoVisible ? hideHeatmapInfo : showHeatmapInfo}
                                style={{
                                    cursor: 'pointer',
                                    background: heatmapInfoVisible ? 'hsla(17, 100%, 47%, 1)' : 'hsla(17, 84%, 95%, 1)',
                                    color: heatmapInfoVisible ? '#FFEB3B' : 'hsl(17, 64%, 32%)',
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
                        extensionPercentage={actionsExtensionPercentage}
                        rotationFixer={(r) => (side === 'right' && r < 0 ? 360 : 0)}
                        label={buttonActionsVisible && (!allActionsLoading || actionCount > 0) ? null : 'Actions'}
                        labelPosition={side === 'left' ? 'right' : 'left'}
                        labelStyle={{
                            opacity: actionsExtensionPercentage > 0.8 ? (actionsExtensionPercentage - 0.8) / 0.2 : 0,
                        }}
                        content={
                            <AimOutlined
                                style={{ fontSize: '28px', color: buttonActionsVisible ? '#fef5e2' : '#f1aa04' }}
                            />
                        }
                        zIndex={1}
                        onClick={buttonActionsVisible ? hideButtonActions : showButtonActions}
                        style={{
                            cursor: 'pointer',
                            transform: `scale(${0.2 + 0.8 * actionsExtensionPercentage})`,
                            background: buttonActionsVisible ? '#f1aa04' : '#fef5e2',
                            borderRadius,
                        }}
                    >
                        {buttonActionsVisible && (!allActionsLoading || actionCount > 0) ? (
                            <Circle
                                width={26}
                                x={
                                    (side === 'left' ? 50 : -50) *
                                    actionsExtensionPercentage *
                                    actionsExtensionPercentage
                                }
                                y={0}
                                content={
                                    <Tooltip
                                        visible={showActionsTooltip}
                                        title="Click for details"
                                        placement={side === 'left' ? 'right' : 'left'}
                                        getPopupContainer={getShadowRootPopupContainer}
                                    >
                                        <div style={{ whiteSpace: 'nowrap', textAlign: 'center' }}>{actionCount}</div>
                                    </Tooltip>
                                }
                                zIndex={4}
                                onClick={actionsInfoVisible ? hideActionsInfo : showActionsInfo}
                                style={{
                                    cursor: 'pointer',
                                    background: actionsInfoVisible ? '#f1aa04' : '#fef5e2',
                                    color: actionsInfoVisible ? '#fef5e2' : '#f1aa04',
                                    width: 'auto',
                                    minWidth: 26,
                                    fontSize: '20px',
                                    lineHeight: '26px',
                                    padding: '0 4px',
                                    transform: `scale(${0.2 + 0.8 * actionsExtensionPercentage})`,
                                    borderRadius: 7,
                                }}
                            />
                        ) : null}
                    </Circle>
                    {showFeatureFlags ? (
                        <Circle
                            width={buttonWidth}
                            x={side === 'left' ? 80 : -80}
                            y={toolbarListVerticalPadding + n++ * 60}
                            extensionPercentage={featureFlagsExtensionPercentage}
                            rotationFixer={(r) => (side === 'right' && r < 0 ? 360 : 0)}
                            label="Feature Flags"
                            labelPosition={side === 'left' ? 'right' : 'left'}
                            labelStyle={{
                                opacity:
                                    featureFlagsExtensionPercentage > 0.8
                                        ? (featureFlagsExtensionPercentage - 0.8) / 0.2
                                        : 0,
                            }}
                            content={<Flag style={{ height: 29 }} engaged={flagsVisible} />}
                            zIndex={1}
                            onClick={flagsVisible ? hideFlags : showFlags}
                            style={{
                                cursor: 'pointer',
                                transform: `scale(${0.2 + 0.8 * featureFlagsExtensionPercentage})`,
                                background: flagsVisible ? '#94D674' : '#D6EBCC',
                                borderRadius,
                            }}
                        />
                    ) : null}
                </>
            ) : null}
        </Circle>
    )
}
