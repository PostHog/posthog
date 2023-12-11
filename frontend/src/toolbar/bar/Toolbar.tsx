import './Toolbar.scss'

import {
    IconBolt,
    IconCursorClick,
    IconDay,
    IconLogomark,
    IconNight,
    IconQuestion,
    IconToggle,
    IconX,
} from '@posthog/icons'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { IconFlare, IconMenu, IconTarget } from 'lib/lemon-ui/icons'
import { LemonMenu, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { useEffect, useRef } from 'react'

import { ActionsToolbarMenu } from '~/toolbar/actions/ActionsToolbarMenu'
import { toolbarLogic } from '~/toolbar/bar/toolbarLogic'
import { FlagsToolbarMenu } from '~/toolbar/flags/FlagsToolbarMenu'
import { HeatmapToolbarMenu } from '~/toolbar/stats/HeatmapToolbarMenu'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'

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
                              label: 'Hedgehog accessories',
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
            <ToolbarButton icon={<IconMenu />} title="More options" />
        </LemonMenu>
    )
}

export function ToolbarInfoMenu(): JSX.Element {
    const ref = useRef<HTMLDivElement | null>(null)
    const { visibleMenu, isDragging, menuProperties, minimized } = useValues(toolbarLogic)
    const { setMenu } = useActions(toolbarLogic)

    const content = minimized ? null : visibleMenu === 'flags' ? (
        <FlagsToolbarMenu />
    ) : visibleMenu === 'heatmap' ? (
        <HeatmapToolbarMenu />
    ) : visibleMenu === 'actions' ? (
        <ActionsToolbarMenu />
    ) : visibleMenu === 'hedgehog' ? (
        <HedgehogMenu />
    ) : null

    useEffect(() => {
        setMenu(ref.current)
        return () => setMenu(null)
    }, [ref.current])

    return (
        <div
            className={clsx(
                'ToolbarMenu',
                !!content && 'ToolbarMenu--visible',
                isDragging && 'ToolbarMenu--dragging',
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

export function Toolbar(): JSX.Element {
    const ref = useRef<HTMLDivElement | null>(null)
    const { minimized, dragPosition, isDragging, hedgehogMode } = useValues(toolbarLogic)
    const { setVisibleMenu, toggleMinimized, onMouseDown, setElement } = useActions(toolbarLogic)
    const { isAuthenticated, userIntent } = useValues(toolbarConfigLogic)
    const { authenticate } = useActions(toolbarConfigLogic)

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
    }, [userIntent])

    return (
        <>
            <ToolbarInfoMenu />
            <div
                ref={ref}
                className={clsx(
                    'Toolbar',
                    minimized && 'Toolbar--minimized',
                    !isAuthenticated && 'Toolbar--unauthenticated',
                    hedgehogMode && 'Toolbar--hedgehog-mode',
                    isDragging && 'Toolbar--dragging'
                )}
                onMouseDown={(e) => onMouseDown(e as any)}
                // eslint-disable-next-line react/forbid-dom-props
                style={
                    {
                        '--toolbar-button-x': `${dragPosition.x}px`,
                        '--toolbar-button-y': `${dragPosition.y}px`,
                    } as any
                }
            >
                <ToolbarButton
                    icon={<IconLogomark />}
                    onClick={isAuthenticated ? toggleMinimized : authenticate}
                    title={isAuthenticated ? 'Minimize' : 'Authenticate the PostHog Toolbar'}
                    titleMinimized={isAuthenticated ? 'Expand the toolbar' : 'Authenticate the PostHog Toolbar'}
                />
                {isAuthenticated ? (
                    <>
                        <ToolbarButton icon={<IconTarget />} menuId="inspect" />
                        <ToolbarButton icon={<IconCursorClick />} menuId="heatmap" />
                        <ToolbarButton icon={<IconBolt />} menuId="actions" />
                        <ToolbarButton icon={<IconToggle />} menuId="flags" title="Feature flags" />
                    </>
                ) : null}

                <MoreMenu />
            </div>
        </>
    )
}
