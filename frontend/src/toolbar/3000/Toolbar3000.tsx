// import { HeatmapStats } from '~/toolbar/stats/HeatmapStats'
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
// import { ActionsTab } from '~/toolbar/actions/ActionsTab'
//
// import { FeatureFlags } from '~/toolbar/flags/FeatureFlags'
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
import { MenuHeader as FlagsMenuHeader } from '~/toolbar/flags/MenuHeader'
import { MenuHeader as ActionsMenuHeader } from '~/toolbar/actions/MenuHeader'
import { MenuHeader as HeatmapMenuHeader } from '~/toolbar/stats/MenuHeader'

import { MenuBody as HeatmapMenuBody } from '~/toolbar/stats/MenuBody'
import { MenuBody as ActionsMenuBody } from '~/toolbar/actions/MenuBody'

import { MenuFooter as ActionsMenuFooter } from '~/toolbar/actions/MenuFooter'

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
//
// /**
//  * Some toolbar modes show a peek of information before opening the full menu.
//  * */
// function PeekMenu(): JSX.Element | null {
//     const { menuPlacement, fullMenuVisible, heatmapInfoVisible, actionsInfoVisible } = useValues(toolbarButtonLogic)
//     const { showHeatmapInfo, hideHeatmapInfo, showActionsInfo, hideActionsInfo } = useActions(toolbarButtonLogic)
//
//     const { buttonActionsVisible } = useValues(actionsTabLogic)
//     const { hideButtonActions } = useActions(actionsTabLogic)
//     const { actionCount, allActionsLoading } = useValues(actionsLogic)
//
//     const { heatmapEnabled, heatmapLoading, elementCount } = useValues(heatmapLogic)
//
//     // const { countFlagsOverridden } = useValues(featureFlagsLogic)
//
//     const peekMenuVisible = !fullMenuVisible && (heatmapEnabled || buttonActionsVisible)
//
//     const clickHandler = heatmapEnabled
//         ? heatmapInfoVisible
//             ? hideHeatmapInfo
//             : showHeatmapInfo
//         : buttonActionsVisible
//         ? actionsInfoVisible
//             ? () => {
//                   hideActionsInfo()
//                   hideButtonActions()
//               }
//             : showActionsInfo
//         : () => {}
//
//     if (!peekMenuVisible) {
//         return null
//     } else {
//         const title = heatmapEnabled ? (
//             <>Heatmap: {heatmapLoading ? <Spinner textColored={true} /> : <>{elementCount} elements</>}</>
//         ) : buttonActionsVisible ? (
//             <>
//                 Actions:{' '}
//                 <div className="whitespace-nowrap text-center">
//                     {allActionsLoading ? (
//                         <Spinner textColored={true} />
//                     ) : (
//                         <LemonBadge.Number size={'small'} count={actionCount} showZero />
//                     )}
//                 </div>
//             </>
//         ) : null
//
//         return (
//             <div
//                 className={
//                     'flex flex-row gap-2 w-full items-center align-center justify-between px-2 pt-1 cursor-pointer'
//                 }
//                 onClick={clickHandler}
//             >
//                 <div className={'flex flex-grow'}>
//                     <h5 className={'flex flex-row items-center mb-0'}>{title}</h5>
//                 </div>
//                 <LemonButton
//                     size={'small'}
//                     icon={menuPlacement === 'top' ? <IconArrowUp /> : <IconArrowDown />}
//                     status={'stealth'}
//                     onClick={clickHandler}
//                 />
//
//                 {/*{flagsVisible ? (*/}
//                 {/*    <div className={'flex flex-grow'}>*/}
//                 {/*        <h5 className={'flex flex-row items-center mb-0'}>*/}
//                 {/*            Feature flags: {countFlagsOverridden} overridden*/}
//                 {/*        </h5>*/}
//                 {/*    </div>*/}
//                 {/*) : null}*/}
//             </div>
//         )
//     }
// }

function ButtonMenu(): JSX.Element {
    const { visibleMenu } = useValues(toolbarButtonLogic)

    const header =
        visibleMenu === 'heatmap' ? (
            <HeatmapMenuHeader />
        ) : visibleMenu === 'actions' ? (
            <ActionsMenuHeader />
        ) : (
            <FlagsMenuHeader />
        )

    const body =
        visibleMenu === 'heatmap' ? <HeatmapMenuBody /> : visibleMenu === 'actions' ? <ActionsMenuBody /> : null

    const footer = visibleMenu === 'heatmap' ? null : visibleMenu === 'actions' ? <ActionsMenuFooter /> : null

    return (
        <div className={clsx('space-y-2 w-full h-full flex flex-col')}>
            {header}

            <div className={clsx('flex flex-col flex-1 space-y-2 h-full overflow-hidden overflow-y-scroll px-2')}>
                {body}
            </div>

            <div className={clsx('flex flex-row space-y-2 px-2 py-1')}>{footer}</div>
        </div>
    )
}

function FullMenu(): JSX.Element {
    return ButtonMenu()
    // const { visibleMenu } = useValues(toolbarButtonLogic)
    //
    // return (
    //     <>
    //         {visibleMenu === 'heatmap' ? <HeatmapStats /> : null}
    //         {visibleMenu === 'actions' ? <ActionsTab /> : null}
    //         {visibleMenu === 'flags' ? <FeatureFlags /> : null}
    //     </>
    // )
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
            <FullMenu />
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
        // close the last opened thing
        // TODO is this necessary without PEEK mode
        setVisibleMenu('none')
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
