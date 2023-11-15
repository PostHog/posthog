import { LemonButton } from 'lib/lemon-ui/LemonButton'
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
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { getToolbarContainer } from '~/toolbar/utils'
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
import { Tooltip } from '@posthog/lemon-ui'
import { useLongPress } from 'lib/hooks/useLongPress'

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
            placement={'top-start'}
            fallbackPlacements={['bottom-start']}
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
                    onClick: () => {
                        toggleTheme()
                    },
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
            <LemonButton
                status={'stealth'}
                icon={<IconMenu />}
                title={'More'}
                // long press so that you can distinguish between drag and click
                {...useLongPress(
                    (clicked) => {
                        if (clicked) {
                            visibleMenu === 'more' ? setVisibleMenu('none') : setVisibleMenu('more')
                        }
                    },
                    {
                        ms: undefined,
                        clickMs: 1 as any,
                        touch: true,
                        click: true,
                    }
                )}
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
                className={clsx(
                    'Toolbar3000 h-10 rounded-lg flex flex-row items-center floating-toolbar-button overflow-hidden',
                    minimizedWidth && 'Toolbar3000--minimized-width'
                )}
            >
                <Tooltip title={minimizedWidth ? 'expand the toolbar' : 'minimize'}>
                    <LemonButton
                        icon={<IconLogomark />}
                        status={'stealth'}
                        // long press so that you can distinguish between drag and click
                        {...useLongPress(
                            (clicked) => {
                                if (clicked) {
                                    toggleWidth()
                                }
                            },
                            {
                                ms: undefined,
                                clickMs: 1 as any,
                                touch: true,
                                click: true,
                            }
                        )}
                        className={clsx(!minimizedWidth && 'ToolbarMenu__logo--minimized-width')}
                    />
                </Tooltip>
                {!minimizedWidth ? <LemonDivider vertical={true} className={'h-full bg-border-bold-3000'} /> : null}
                {isAuthenticated ? (
                    <>
                        <Tooltip title={'Inspect'}>
                            <LemonButton
                                icon={<IconSearch />}
                                aria-label={'Inspect'}
                                status={'stealth'}
                                // long press so that you can distinguish between drag and click
                                {...useLongPress(
                                    (clicked) => {
                                        if (clicked) {
                                            visibleMenu === 'inspect'
                                                ? setVisibleMenu('none')
                                                : setVisibleMenu('inspect')
                                        }
                                    },
                                    {
                                        ms: undefined,
                                        clickMs: 1 as any,
                                        touch: true,
                                        click: true,
                                    }
                                )}
                                active={visibleMenu === 'inspect'}
                                square={true}
                            />
                        </Tooltip>
                        <Tooltip title={'Heatmap'}>
                            <LemonButton
                                aria-label={'Heatmap'}
                                icon={<IconCursorClick />}
                                status={'stealth'}
                                // long press so that you can distinguish between drag and click
                                {...useLongPress(
                                    (clicked) => {
                                        if (clicked) {
                                            visibleMenu === 'heatmap'
                                                ? setVisibleMenu('none')
                                                : setVisibleMenu('heatmap')
                                        }
                                    },
                                    {
                                        ms: undefined,
                                        clickMs: 1 as any,
                                        touch: true,
                                        click: true,
                                    }
                                )}
                                active={visibleMenu === 'heatmap'}
                                square={true}
                            />
                        </Tooltip>
                        <Tooltip title={'Actions'}>
                            <LemonButton
                                aria-label={'Actions'}
                                icon={<IconTarget />}
                                status={'stealth'}
                                // long press so that you can distinguish between drag and click
                                {...useLongPress(
                                    (clicked) => {
                                        if (clicked) {
                                            visibleMenu === 'actions'
                                                ? setVisibleMenu('none')
                                                : setVisibleMenu('actions')
                                        }
                                    },
                                    {
                                        ms: undefined,
                                        clickMs: 1 as any,
                                        touch: true,
                                        click: true,
                                    }
                                )}
                                active={visibleMenu === 'actions'}
                                square={true}
                            />
                        </Tooltip>
                        <Tooltip title={'Feature flags'}>
                            <LemonButton
                                aria-label={'Feature flags'}
                                icon={<IconToggle />}
                                status={'stealth'}
                                // long press so that you can distinguish between drag and click
                                {...useLongPress(
                                    (clicked) => {
                                        if (clicked) {
                                            visibleMenu === 'flags' ? setVisibleMenu('none') : setVisibleMenu('flags')
                                        }
                                    },
                                    {
                                        ms: undefined,
                                        clickMs: 1 as any,
                                        touch: true,
                                        click: true,
                                    }
                                )}
                                active={visibleMenu === 'flags'}
                                square={true}
                            />
                        </Tooltip>
                        <MoreMenu />
                    </>
                ) : null}
            </div>
        </>
    )
}
