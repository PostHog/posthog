import './Toolbar.scss'

import {
    IconBolt,
    IconCursorClick,
    IconDay,
    IconLive,
    IconLogomark,
    IconNight,
    IconQuestion,
    IconSearch,
    IconTestTube,
    IconToggle,
    IconX,
} from '@posthog/icons'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { IconFlare, IconMenu } from 'lib/lemon-ui/icons'
import { LemonMenu, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { useEffect, useRef } from 'react'

import { ActionsToolbarMenu } from '~/toolbar/actions/ActionsToolbarMenu'
import { toolbarLogic } from '~/toolbar/bar/toolbarLogic'
import { EventDebugMenu } from '~/toolbar/debug/EventDebugMenu'
import { ExperimentsToolbarMenu } from '~/toolbar/experiments/ExperimentsToolbarMenu'
import { FlagsToolbarMenu } from '~/toolbar/flags/FlagsToolbarMenu'
import { HeatmapToolbarMenu } from '~/toolbar/stats/HeatmapToolbarMenu'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { useToolbarFeatureFlag } from '~/toolbar/toolbarPosthogJS'

import { HedgehogMenu } from '../hedgehog/HedgehogMenu'
import { ToolbarButton } from './ToolbarButton'

const HELP_URL = 'https://posthog.com/docs/user-guides/toolbar?utm_medium=in-product&utm_campaign=toolbar-help-button'

function MoreMenu(): JSX.Element {
    const { hedgehogMode, theme } = useValues(toolbarLogic)
    const { setHedgehogMode, toggleTheme, setVisibleMenu } = useActions(toolbarLogic)

    // KLUDGE: if there is no theme, assume light mode, which shouldn't be, but seems to be, necessary
    const currentlyLightMode = !theme || theme === 'light'

    const { logout } = useActions(toolbarConfigLogic)

    return (
        <LemonMenu
            placement="top-end"
            fallbackPlacements={['bottom-end']}
            items={
                [
                    {
                        icon: <>🦔</>,
                        label: hedgehogMode ? 'Disable hedgehog mode' : 'Hedgehog mode',
                        onClick: () => {
                            setHedgehogMode(!hedgehogMode)
                        },
                    },
                    hedgehogMode
                        ? {
                              icon: <IconFlare />,
                              label: 'Hedgehog options',
                              onClick: () => {
                                  setVisibleMenu('hedgehog')
                              },
                          }
                        : undefined,
                    {
                        icon: currentlyLightMode ? <IconNight /> : <IconDay />,
                        label: `Switch to ${currentlyLightMode ? 'dark' : 'light'} mode`,
                        onClick: () => toggleTheme(),
                    },
                    {
                        icon: <IconQuestion />,
                        label: 'Help',
                        onClick: () => {
                            window.open(HELP_URL, '_blank')?.focus()
                        },
                    },
                    { icon: <IconX />, label: 'Close toolbar', onClick: logout },
                ].filter(Boolean) as LemonMenuItems
            }
            maxContentWidth={true}
        >
            <ToolbarButton title="More options">
                <IconMenu />
            </ToolbarButton>
        </LemonMenu>
    )
}

export function ToolbarInfoMenu(): JSX.Element | null {
    const ref = useRef<HTMLDivElement | null>(null)
    const { visibleMenu, isDragging, menuProperties, minimized, isBlurred } = useValues(toolbarLogic)
    const { setMenu } = useActions(toolbarLogic)
    const { isAuthenticated } = useValues(toolbarConfigLogic)
    const showExperiments = useToolbarFeatureFlag('web-experiments')
    const content = minimized ? null : visibleMenu === 'flags' ? (
        <FlagsToolbarMenu />
    ) : visibleMenu === 'heatmap' ? (
        <HeatmapToolbarMenu />
    ) : visibleMenu === 'actions' ? (
        <ActionsToolbarMenu />
    ) : visibleMenu === 'hedgehog' ? (
        <HedgehogMenu />
    ) : visibleMenu === 'debugger' ? (
        <EventDebugMenu />
    ) : visibleMenu === 'experiments' && showExperiments ? (
        <ExperimentsToolbarMenu />
    ) : null

    useEffect(() => {
        setMenu(ref.current)
        return () => setMenu(null)
    }, [ref.current])

    if (!isAuthenticated) {
        return null
    }

    return (
        <div
            className={clsx(
                'ToolbarMenu',
                !!content && 'ToolbarMenu--visible',
                isDragging && 'ToolbarMenu--dragging',
                isBlurred && 'ToolbarMenu--blurred',
                menuProperties.isBelow && 'ToolbarMenu--below'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                transform: menuProperties.transform,
            }}
        >
            <div
                ref={ref}
                className="ToolbarMenu__content"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    maxHeight: menuProperties.maxHeight,
                }}
            >
                {content}
            </div>
        </div>
    )
}

export function Toolbar(): JSX.Element | null {
    const ref = useRef<HTMLDivElement | null>(null)
    const { minimized, position, isDragging, hedgehogMode, isEmbeddedInApp } = useValues(toolbarLogic)
    const { setVisibleMenu, toggleMinimized, onMouseOrTouchDown, setElement, setIsBlurred } = useActions(toolbarLogic)
    const { isAuthenticated, userIntent } = useValues(toolbarConfigLogic)
    const { authenticate } = useActions(toolbarConfigLogic)
    const showExperiments = useToolbarFeatureFlag('web-experiments')

    useEffect(() => {
        setElement(ref.current)
        return () => setElement(null)
    }, [ref.current])

    useKeyboardHotkeys(
        {
            escape: { action: () => setVisibleMenu('none'), willHandleEvent: true },
        },
        []
    )

    useEffect(() => {
        if (userIntent === 'add-action' || userIntent === 'edit-action') {
            setVisibleMenu('actions')
        }

        if (userIntent === 'heatmaps') {
            setVisibleMenu('heatmap')
        }
    }, [userIntent])

    if (isEmbeddedInApp) {
        return null
    }
    return (
        <>
            <ToolbarInfoMenu />
            <div
                ref={ref}
                className={clsx(
                    'Toolbar',
                    minimized && 'Toolbar--minimized',
                    hedgehogMode && 'Toolbar--hedgehog-mode',
                    isDragging && 'Toolbar--dragging'
                )}
                onMouseDown={(e) => onMouseOrTouchDown(e.nativeEvent)}
                onTouchStart={(e) => onMouseOrTouchDown(e.nativeEvent)}
                onMouseOver={() => setIsBlurred(false)}
                // eslint-disable-next-line react/forbid-dom-props
                style={
                    {
                        '--toolbar-button-x': `${position.x}px`,
                        '--toolbar-button-y': `${position.y}px`,
                    } as any
                }
            >
                <ToolbarButton
                    onClick={isAuthenticated ? toggleMinimized : authenticate}
                    title={isAuthenticated ? 'Minimize' : 'Authenticate the PostHog Toolbar'}
                    titleMinimized={isAuthenticated ? 'Expand the toolbar' : 'Authenticate the PostHog Toolbar'}
                >
                    <IconLogomark />
                </ToolbarButton>
                {isAuthenticated ? (
                    <>
                        <ToolbarButton menuId="inspect">
                            <IconSearch />
                        </ToolbarButton>
                        <ToolbarButton menuId="heatmap">
                            <IconCursorClick />
                        </ToolbarButton>
                        <ToolbarButton menuId="actions">
                            <IconBolt />
                        </ToolbarButton>
                        <ToolbarButton menuId="flags" title="Feature flags">
                            <IconToggle />
                        </ToolbarButton>
                        <ToolbarButton menuId="debugger" title="Event debugger">
                            <IconLive />
                        </ToolbarButton>
                        {showExperiments && (
                            <ToolbarButton menuId="experiments" title="Experiments">
                                <IconTestTube />
                            </ToolbarButton>
                        )}
                    </>
                ) : (
                    <ToolbarButton flex onClick={authenticate}>
                        Authenticate
                    </ToolbarButton>
                )}

                <MoreMenu />
            </div>
        </>
    )
}
