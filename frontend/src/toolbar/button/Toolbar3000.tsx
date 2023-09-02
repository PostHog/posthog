import { HeatmapStats } from '~/toolbar/stats/HeatmapStats'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import {
    IconArrowDown,
    IconArrowUp,
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
import { ActionsTab } from '~/toolbar/actions/ActionsTab'
import { LemonBadge } from 'lib/lemon-ui/LemonBadge'
import { FeatureFlags } from '~/toolbar/flags/FeatureFlags'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { getToolbarContainer } from '~/toolbar/utils'
import { Logomark as Logomark3000 } from '~/toolbar/button/icons/icons'
import { useActions, useValues } from 'kea'
import { toolbarButtonLogic } from '~/toolbar/button/toolbarButtonLogic'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { actionsLogic } from '~/toolbar/actions/actionsLogic'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { heatmapLogic } from '~/toolbar/elements/heatmapLogic'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { featureFlagsLogic } from '~/toolbar/flags/featureFlagsLogic'
import { HELP_URL } from './ToolbarButton'
import { useLayoutEffect, useRef } from 'react'

function MoreMenu({
    onOpenOrClose,
}: {
    onOpenOrClose: (e: React.MouseEvent, actionFn: () => void) => void
}): JSX.Element {
    const { moreMenuVisible, theme } = useValues(toolbarButtonLogic)
    const { setHedgehogMode, closeMoreMenu, openMoreMenu, toggleTheme } = useActions(toolbarButtonLogic)

    const { logout } = useActions(toolbarLogic)

    return (
        <LemonMenu
            visible={moreMenuVisible}
            onVisibilityChange={(visible) => {
                if (!visible && moreMenuVisible) {
                    closeMoreMenu()
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
                    icon: theme === 'light' ? <IconDarkMode /> : <IconLightMode />,
                    label: `Switch to ${theme === 'light' ? 'dark' : 'light'} mode`,
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
                    onOpenOrClose(e, moreMenuVisible ? closeMoreMenu : openMoreMenu)
                }}
            />
        </LemonMenu>
    )
}

/**
 * Some toolbar modes show a peek of information before opening the full menu.
 * */
function PeekMenu(): JSX.Element {
    const { heatmapInfoVisible, actionsInfoVisible, flagsVisible } = useValues(toolbarButtonLogic)
    const { showHeatmapInfo, hideHeatmapInfo, showActionsInfo, hideActionsInfo } = useActions(toolbarButtonLogic)

    const { buttonActionsVisible } = useValues(actionsTabLogic)
    const { hideButtonActions } = useActions(actionsTabLogic)
    const { actionCount, allActionsLoading } = useValues(actionsLogic)

    const { heatmapEnabled, heatmapLoading, elementCount } = useValues(heatmapLogic)

    const { countFlagsOverridden } = useValues(featureFlagsLogic)

    return (
        <div className={'flex flex-row gap-2 w-full items-center justify-between px-2 pt-1 h-12'}>
            {heatmapEnabled ? (
                <>
                    <div className={'flex flex-grow'}>
                        <h5 className={'flex flex-row items-center'}>
                            Heatmap: {heatmapLoading ? <Spinner textColored={true} /> : <>{elementCount} elements</>}
                        </h5>
                    </div>
                    <LemonButton
                        size={'small'}
                        icon={heatmapInfoVisible ? <IconArrowDown /> : <IconArrowUp />}
                        status={'stealth'}
                        onClick={heatmapInfoVisible ? hideHeatmapInfo : showHeatmapInfo}
                        active={heatmapInfoVisible}
                    />
                </>
            ) : null}

            {buttonActionsVisible ? (
                <>
                    <div className={'flex flex-grow'}>
                        <h5 className={'flex flex-row items-center'}>
                            Actions:{' '}
                            <div className="whitespace-nowrap text-center">
                                {allActionsLoading ? (
                                    <Spinner textColored={true} />
                                ) : (
                                    <LemonBadge.Number size={'small'} count={actionCount} showZero />
                                )}
                            </div>
                        </h5>
                    </div>
                    <LemonButton
                        size={'small'}
                        icon={actionsInfoVisible ? <IconArrowDown /> : <IconArrowUp />}
                        status={'stealth'}
                        onClick={
                            actionsInfoVisible
                                ? () => {
                                      hideActionsInfo()
                                      hideButtonActions()
                                  }
                                : showActionsInfo
                        }
                        active={actionsInfoVisible}
                    />
                </>
            ) : null}

            {flagsVisible ? (
                <div className={'flex flex-grow'}>
                    <h5 className={'flex flex-row items-center'}>Feature flags: {countFlagsOverridden} overridden</h5>
                </div>
            ) : null}
        </div>
    )
}

function FullMenu(): JSX.Element {
    const { heatmapInfoVisible, actionsInfoVisible, flagsVisible } = useValues(toolbarButtonLogic)

    return (
        <>
            {heatmapInfoVisible ? <HeatmapStats /> : null}
            {actionsInfoVisible ? <ActionsTab /> : null}
            {flagsVisible ? <FeatureFlags /> : null}
        </>
    )
}

function ToolbarInfoMenu(): JSX.Element {
    const menuRef = useRef<HTMLDivElement | null>(null)
    const { dragPosition } = useValues(toolbarButtonLogic)
    const { heatmapInfoVisible, actionsInfoVisible, flagsVisible } = useValues(toolbarButtonLogic)
    const { heatmapEnabled } = useValues(heatmapLogic)
    const { inspectEnabled } = useValues(elementsLogic)
    const { buttonActionsVisible } = useValues(actionsTabLogic)

    useLayoutEffect(() => {
        if (!menuRef.current) {
            return
        }

        const peekIsShowing = heatmapEnabled || buttonActionsVisible
        const fullIsShowing = heatmapInfoVisible || actionsInfoVisible || flagsVisible

        if (peekIsShowing && !fullIsShowing) {
            menuRef.current.style.height = 'auto'
        } else if (fullIsShowing) {
            const heightAvailableForMenu = menuRef.current.getBoundingClientRect().bottom
            menuRef.current.style.height = `${heightAvailableForMenu - 10}px`

            // TODO what if there is less than 10 available
        } else {
            menuRef.current.style.height = '0px'
        }
    }, [
        dragPosition,
        menuRef,
        heatmapInfoVisible,
        actionsInfoVisible,
        flagsVisible,
        inspectEnabled,
        heatmapEnabled,
        buttonActionsVisible,
    ])

    return (
        <div
            ref={menuRef}
            className={
                'absolute bottom Toolbar3000 justify-between Toolbar3000__menu w-auto mx-2 rounded-t flex flex-col items-center'
            }
        >
            <FullMenu />
            <PeekMenu />
        </div>
    )
}

export function Toolbar3000(): JSX.Element {
    const { flagsVisible, closeTheLastOpenedMenu } = useValues(toolbarButtonLogic)
    const { showFlags, hideFlags } = useActions(toolbarButtonLogic)

    const { buttonActionsVisible } = useValues(actionsTabLogic)
    const { hideButtonActions, showButtonActions } = useActions(actionsTabLogic)

    const { enableInspect, disableInspect } = useActions(elementsLogic)
    const { inspectEnabled } = useValues(elementsLogic)

    const { enableHeatmap, disableHeatmap } = useActions(heatmapLogic)
    const { heatmapEnabled } = useValues(heatmapLogic)

    const { isAuthenticated } = useValues(toolbarLogic)

    const swallowClick = (e: React.MouseEvent, actionFn: () => void): void => {
        // swallow the click
        e.preventDefault()
        e.stopPropagation()
        // close the last opened thing
        closeTheLastOpenedMenu?.()
        // carry out the action
        actionFn()
    }

    return (
        <div className={'relative'}>
            <ToolbarInfoMenu />
            <div className={'Toolbar3000 px-2 w-auto h-10 space-x-2 rounded-lg flex flex-row items-center'}>
                <IconDragHandle className={'text-2xl floating-toolbar-button cursor-grab'} />
                <LemonDivider vertical={true} className={'h-full bg-border-bold-3000'} />
                {isAuthenticated ? (
                    <>
                        <LemonButton
                            title={'Inspect'}
                            icon={<IconMagnifier />}
                            status={'stealth'}
                            onClick={(e) => swallowClick(e, inspectEnabled ? disableInspect : enableInspect)}
                            active={inspectEnabled}
                        />
                        <LemonButton
                            title={'Heatmap'}
                            icon={<IconClick />}
                            status={'stealth'}
                            onClick={(e) => swallowClick(e, heatmapEnabled ? disableHeatmap : enableHeatmap)}
                            active={heatmapEnabled}
                        />
                        <LemonButton
                            title={'Actions'}
                            icon={<IconTarget />}
                            status={'stealth'}
                            onClick={(e) =>
                                swallowClick(e, buttonActionsVisible ? hideButtonActions : showButtonActions)
                            }
                            active={buttonActionsVisible}
                        />
                        <LemonButton
                            title={'Feature flags'}
                            icon={<IconFlag />}
                            status={'stealth'}
                            onClick={(e) => swallowClick(e, flagsVisible ? hideFlags : showFlags)}
                            active={flagsVisible}
                        />
                        <MoreMenu onOpenOrClose={swallowClick} />
                        <LemonDivider vertical={true} className={'h-full bg-border-bold-3000'} />
                    </>
                ) : null}
                <Logomark3000 />
            </div>
        </div>
    )
}
