import {
    IconX,
    IconLogomark,
    IconSearch,
    IconNight,
    IconDay,
    IconToggle,
    IconCursorClick,
    IconQuestion,
} from '@posthog/icons'
import { IconMenu, IconTarget } from 'lib/lemon-ui/icons'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { getToolbarContainer } from '~/toolbar/utils'
import { useActions, useValues } from 'kea'
import { toolbarButtonLogic } from '~/toolbar/button/toolbarButtonLogic'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { useEffect, useRef } from 'react'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import clsx from 'clsx'
import { FlagsToolbarMenu } from '~/toolbar/flags/FlagsToolbarMenu'
import { HeatmapToolbarMenu } from '~/toolbar/stats/HeatmapToolbarMenu'
import { ActionsToolbarMenu } from '~/toolbar/actions/ActionsToolbarMenu'
import { Toolbar3000Button } from './Toolbar3000Button'

import './Toolbar3000.scss'

const HELP_URL = 'https://posthog.com/docs/user-guides/toolbar?utm_medium=in-product&utm_campaign=toolbar-help-button'

function MoreMenu(): JSX.Element {
    const { hedgehogMode, theme } = useValues(toolbarButtonLogic)
    const { setHedgehogMode, toggleTheme } = useActions(toolbarButtonLogic)

    // KLUDGE: if there is no theme, assume light mode, which shouldn't be, but seems to be, necessary
    const currentlyLightMode = !theme || theme === 'light'

    const { logout } = useActions(toolbarLogic)

    return (
        <LemonMenu
            placement="top-end"
            fallbackPlacements={['bottom-end']}
            getPopupContainer={getToolbarContainer}
            items={[
                {
                    icon: <>🦔</>,
                    label: 'Hedgehog mode',
                    onClick: () => {
                        setHedgehogMode(!hedgehogMode)
                    },
                },
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
                { icon: <IconX />, label: 'Logout', onClick: logout },
            ]}
            maxContentWidth={true}
        >
            <Toolbar3000Button icon={<IconMenu />} />
        </LemonMenu>
    )
}

function ToolbarInfoMenu(): JSX.Element {
    const ref = useRef<HTMLDivElement | null>(null)
    const { visibleMenu, isDragging, menuProperties, minimized } = useValues(toolbarButtonLogic)
    const { setMenu } = useActions(toolbarButtonLogic)

    const content = minimized ? null : visibleMenu === 'flags' ? (
        <FlagsToolbarMenu />
    ) : visibleMenu === 'heatmap' ? (
        <HeatmapToolbarMenu />
    ) : visibleMenu === 'actions' ? (
        <ActionsToolbarMenu />
    ) : null

    useEffect(() => {
        setMenu(ref.current)
        return () => setMenu(null)
    }, [ref.current])

    return (
        <div
            className={clsx(
                'Toolbar3000Menu',
                !!content && 'Toolbar3000Menu--visible',
                isDragging && 'Toolbar3000Menu--dragging',
                menuProperties.isBelow && 'Toolbar3000Menu--below'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                transform: menuProperties.transform,
            }}
        >
            <div
                ref={ref}
                className="Toolbar3000Menu__content"
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

export function Toolbar3000(): JSX.Element {
    const ref = useRef<HTMLDivElement | null>(null)
    const { minimized, dragPosition, isDragging, hedgehogMode } = useValues(toolbarButtonLogic)
    const { setVisibleMenu, toggleMinimized, onMouseDown, setElement } = useActions(toolbarButtonLogic)
    const { isAuthenticated } = useValues(toolbarLogic)

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

    return (
        <>
            <ToolbarInfoMenu />
            <div
                ref={ref}
                className={clsx(
                    'Toolbar3000',
                    minimized && 'Toolbar3000--minimized',
                    hedgehogMode && 'Toolbar3000--hedgehog-mode',
                    isDragging && 'Toolbar3000--dragging'
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
                <Toolbar3000Button
                    icon={<IconLogomark />}
                    onClick={toggleMinimized}
                    title="Minimize"
                    titleMinimized="Expand the toolbar"
                />
                {isAuthenticated ? (
                    <>
                        <Toolbar3000Button icon={<IconSearch />} menuId="inspect" />
                        <Toolbar3000Button icon={<IconCursorClick />} menuId="heatmap" />
                        <Toolbar3000Button icon={<IconTarget />} menuId="actions" />
                        <Toolbar3000Button icon={<IconToggle />} menuId="flags" title="Feature flags" />
                        <MoreMenu />
                    </>
                ) : null}
            </div>
        </>
    )
}
