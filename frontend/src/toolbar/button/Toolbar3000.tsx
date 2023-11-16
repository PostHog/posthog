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
import { getShadowRoot, getToolbarContainer } from '~/toolbar/utils'
import { useActions, useValues } from 'kea'
import { toolbarButtonLogic } from '~/toolbar/button/toolbarButtonLogic'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { useEffect, useLayoutEffect, useRef } from 'react'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import clsx from 'clsx'
import { FlagsToolbarMenu } from '~/toolbar/flags/FlagsToolbarMenu'
import { HeatmapToolbarMenu } from '~/toolbar/stats/HeatmapToolbarMenu'
import { ActionsToolbarMenu } from '~/toolbar/actions/ActionsToolbarMenu'
import { Toolbar3000Button } from './Toolbar3000Button'

import './Toolbar3000.scss'

const HELP_URL = 'https://posthog.com/docs/user-guides/toolbar?utm_medium=in-product&utm_campaign=toolbar-help-button'

function MoreMenu(): JSX.Element {
    const { visibleMenu, hedgehogMode, theme } = useValues(toolbarButtonLogic)
    const { setHedgehogMode, setVisibleMenu, toggleTheme } = useActions(toolbarButtonLogic)

    // KLUDGE: if there is no theme, assume light mode, which shouldn't be, but seems to be, necessary
    const currentlyLightMode = !theme || theme === 'light'

    const { logout } = useActions(toolbarLogic)

    return (
        <LemonMenu
            visible={visibleMenu === 'more'}
            onVisibilityChange={(visible) => {
                if (!visible && visibleMenu === 'more') {
                    setVisibleMenu('none')
                }
            }}
            placement="top-end"
            fallbackPlacements={['bottom-end']}
            getPopupContainer={getToolbarContainer}
            // onClickOutside={() => {
            //     if (visibleMenu === 'more') {
            //         setVisibleMenu('none')
            //     }
            // }}
            items={[
                {
                    icon: <>🦔</>,
                    label: 'Hedgehog mode',
                    onClick: () => setHedgehogMode(!hedgehogMode),
                },
                {
                    icon: currentlyLightMode ? <IconNight /> : <IconDay />,
                    label: `Switch to ${currentlyLightMode ? 'dark' : 'light'} mode`,
                    onClick: () => toggleTheme(),
                },
                {
                    icon: <IconQuestion />,
                    label: 'Help',
                    onClick: () => window.open(HELP_URL, '_blank')?.focus(),
                },
                { icon: <IconX />, label: 'Logout', onClick: logout },
            ]}
            maxContentWidth={true}
        >
            <Toolbar3000Button icon={<IconMenu />} menuId="more" />
        </LemonMenu>
    )
}

function ToolbarInfoMenu(): JSX.Element {
    const menuRef = useRef<HTMLDivElement | null>(null)
    const { visibleMenu, windowHeight, dragPosition, menuPlacement } = useValues(toolbarButtonLogic)
    const { setMenuPlacement } = useActions(toolbarButtonLogic)

    const fullIsShowing = visibleMenu === 'heatmap' || visibleMenu === 'actions' || visibleMenu === 'flags'

    useLayoutEffect(() => {
        if (!menuRef.current) {
            return
        }

        if (dragPosition.y <= 300) {
            setMenuPlacement('bottom')
        } else {
            setMenuPlacement('top')
        }

        if (fullIsShowing) {
            let heightAvailableForMenu = menuRef.current.getBoundingClientRect().bottom
            if (menuPlacement === 'bottom') {
                heightAvailableForMenu = windowHeight - menuRef.current.getBoundingClientRect().top
            }
            menuRef.current.style.height = `${heightAvailableForMenu - 10}px`

            // TODO what if there is less than 10 available
        } else {
            menuRef.current.style.height = '0px'
        }
    }, [dragPosition, menuRef, fullIsShowing])

    return (
        <div
            ref={menuRef}
            className={clsx(
                'Toolbar3000 Toolbar3000Menu absolute rounded-lg flex flex-col',
                fullIsShowing && 'Toolbar3000Menu--visible',
                menuPlacement === 'top' ? 'bottom' : 'top-12'
            )}
        >
            {visibleMenu === 'flags' ? (
                <FlagsToolbarMenu />
            ) : visibleMenu === 'heatmap' ? (
                <HeatmapToolbarMenu />
            ) : visibleMenu === 'actions' ? (
                <ActionsToolbarMenu />
            ) : null}
        </div>
    )
}

export function Toolbar3000(): JSX.Element {
    const ref = useRef<HTMLDivElement | null>(null)
    const { minimizedWidth, dragPosition } = useValues(toolbarButtonLogic)
    const { setVisibleMenu, toggleWidth, onMouseDown, setElement } = useActions(toolbarButtonLogic)
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
                    'Toolbar3000 Toolbar3000Bar fixed h-10 rounded-lg flex flex-row items-center floating-toolbar-button overflow-hidden',
                    minimizedWidth && 'Toolbar3000--minimized-width'
                )}
                onMouseDown={onMouseDown}
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    top: dragPosition.y,
                    left: dragPosition.x,
                }}
            >
                <Toolbar3000Button
                    icon={<IconLogomark />}
                    onClick={toggleWidth}
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
