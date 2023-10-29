import { LemonButton } from 'lib/lemon-ui/LemonButton'
import {
    IconClick,
    IconClose,
    IconDarkMode,
    IconDragHandle,
    IconFlag,
    IconHelpOutline,
    IconLightMode,
    IconMagnifier,
    IconMenu,
    IconTarget,
} from 'lib/lemon-ui/icons'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { getToolbarContainer } from '~/toolbar/utils'
import { Logomark as Logomark3000 } from '~/toolbar/button/icons/icons'
import { useActions, useValues } from 'kea'
import { toolbarButtonLogic } from '~/toolbar/button/toolbarButtonLogic'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'

import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { HELP_URL } from '../button/ToolbarButton'
import { useLayoutEffect, useRef } from 'react'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import clsx from 'clsx'
import { FlagsToolbarMenu } from '~/toolbar/flags/FlagsToolbarMenu'
import { HeatmapToolbarMenu } from '~/toolbar/stats/HeatmapToolbarMenu'
import { ActionsToolbarMenu } from '~/toolbar/actions/ActionsToolbarMenu'

function MoreMenu({
    onOpenOrClose,
}: {
    onOpenOrClose: (e: React.MouseEvent, actionFn: () => void) => void
}): JSX.Element {
    const { visibleMenu, theme } = useValues(toolbarButtonLogic)
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
            placement={'top-start'}
            fallbackPlacements={['bottom-start']}
            getPopupContainer={getToolbarContainer}
            items={[
                {
                    icon: <>🦔</>,
                    label: 'Hedgehog mode',
                    onClick: () => {
                        setHedgehogMode(true)
                    },
                },
                {
                    icon: currentlyLightMode ? <IconDarkMode /> : <IconLightMode />,
                    label: `Switch to ${currentlyLightMode ? 'dark' : 'light'} mode`,
                    onClick: () => {
                        toggleTheme()
                    },
                },
                {
                    icon: <IconHelpOutline />,
                    label: 'Help',
                    onClick: () => {
                        window.open(HELP_URL, '_blank')?.focus()
                    },
                },
                { icon: <IconClose />, label: 'Logout', onClick: logout },
            ]}
            maxContentWidth={true}
        >
            <LemonButton
                status={'stealth'}
                icon={<IconMenu />}
                title={'More'}
                onClick={(e) => {
                    onOpenOrClose(e, () => (visibleMenu === 'more' ? setVisibleMenu('none') : setVisibleMenu('more')))
                }}
                square={true}
            />
        </LemonMenu>
    )
}

function ToolbarInfoMenu(): JSX.Element {
    const menuRef = useRef<HTMLDivElement | null>(null)
    const { visibleMenu, windowHeight, dragPosition, menuPlacement } = useValues(toolbarButtonLogic)
    const { setMenuPlacement } = useActions(toolbarButtonLogic)
    const { heatmapEnabled } = useValues(heatmapLogic)
    const { inspectEnabled } = useValues(elementsLogic)
    const { buttonActionsVisible } = useValues(actionsTabLogic)

    useLayoutEffect(() => {
        if (!menuRef.current) {
            return
        }

        if (dragPosition.y <= 300) {
            setMenuPlacement('bottom')
        } else {
            setMenuPlacement('top')
        }

        const fullIsShowing = visibleMenu === 'heatmap' || visibleMenu === 'actions' || visibleMenu === 'flags'

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
    }, [dragPosition, menuRef, visibleMenu, inspectEnabled, heatmapEnabled, buttonActionsVisible])

    return (
        <div
            ref={menuRef}
            className={clsx(
                'absolute Toolbar3000 Toolbar3000__menu rounded-lg flex flex-col',
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
    const { visibleMenu, minimizedWidth } = useValues(toolbarButtonLogic)
    const { setVisibleMenu, toggleWidth } = useActions(toolbarButtonLogic)

    const { isAuthenticated } = useValues(toolbarLogic)

    const swallowClick = (e: React.MouseEvent, actionFn: () => void): void => {
        // swallow the click
        e.preventDefault()
        e.stopPropagation()
        // carry out the action
        actionFn()
    }

    useKeyboardHotkeys(
        {
            escape: { action: () => setVisibleMenu('none'), willHandleEvent: true },
        },
        []
    )

    return (
        <>
            {!minimizedWidth && <ToolbarInfoMenu />}
            <div
                className={clsx(
                    'Toolbar3000 px-2 h-10 space-x-2 rounded-lg flex flex-row items-center floating-toolbar-button',
                    minimizedWidth ? 'Toolbar3000--minimized-width' : ''
                )}
            >
                {!minimizedWidth ? (
                    <>
                        <IconDragHandle className={'text-2xl cursor-grab'} />
                        <LemonDivider vertical={true} className={'h-full bg-border-bold-3000'} />
                    </>
                ) : null}
                {isAuthenticated && !minimizedWidth ? (
                    <>
                        <LemonButton
                            title={'Inspect'}
                            icon={<IconMagnifier />}
                            status={'stealth'}
                            onClick={(e) =>
                                swallowClick(e, () =>
                                    visibleMenu === 'inspect' ? setVisibleMenu('none') : setVisibleMenu('inspect')
                                )
                            }
                            active={visibleMenu === 'inspect'}
                            square={true}
                        />
                        <LemonButton
                            title={'Heatmap'}
                            icon={<IconClick />}
                            status={'stealth'}
                            onClick={(e) =>
                                swallowClick(e, () =>
                                    visibleMenu === 'heatmap' ? setVisibleMenu('none') : setVisibleMenu('heatmap')
                                )
                            }
                            active={visibleMenu === 'heatmap'}
                            square={true}
                        />
                        <LemonButton
                            title={'Actions'}
                            icon={<IconTarget />}
                            status={'stealth'}
                            onClick={(e) =>
                                swallowClick(e, () =>
                                    visibleMenu === 'actions' ? setVisibleMenu('none') : setVisibleMenu('actions')
                                )
                            }
                            active={visibleMenu === 'actions'}
                            square={true}
                        />
                        <LemonButton
                            title={'Feature flags'}
                            icon={<IconFlag />}
                            status={'stealth'}
                            onClick={(e) =>
                                swallowClick(e, () =>
                                    visibleMenu === 'flags' ? setVisibleMenu('none') : setVisibleMenu('flags')
                                )
                            }
                            active={visibleMenu === 'flags'}
                            square={true}
                        />
                        <MoreMenu onOpenOrClose={swallowClick} />
                        <LemonDivider vertical={true} className={'h-full bg-border-bold-3000'} />
                    </>
                ) : null}
                <LemonButton
                    icon={<Logomark3000 />}
                    title={minimizedWidth ? 'expand the toolbar' : 'minimize'}
                    status={'stealth'}
                    size={'small'}
                    square={true}
                    noPadding={false}
                    onClick={(e) => {
                        e.stopPropagation()
                        toggleWidth()
                    }}
                />
            </div>
        </>
    )
}
