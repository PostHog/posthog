import { IconAdvanced, IconChat, IconGear, IconInfo, IconShieldLock } from '@posthog/icons'
import { LemonDivider } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { TopBarSettingsButton } from 'lib/components/TopBarSettingsButton/TopBarSettingsButton'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { Label } from 'lib/ui/Label/Label'
import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { sidePanelInfoLogic, SidePanelInfoTab } from './sidePanelInfoLogic'

export function SidePanelInfoContent({ children }: { children: React.ReactNode }): JSX.Element | null {
    const { sidePanelInfoContentElement } = useValues(sidePanelInfoLogic)
    const { setSceneHasSidePanel } = useActions(sidePanelInfoLogic)

    useEffect(() => {
        // Set the scene has side panel to true when the component is mounted
        setSceneHasSidePanel(true)

        // Set the scene has side panel to false when the component is unmounted
        return () => {
            setSceneHasSidePanel(false)
        }
    }, [])

    return (
        <>
            {children &&
                sidePanelInfoContentElement &&
                createPortal(<div className="flex flex-col gap-px">{children}</div>, sidePanelInfoContentElement)}
        </>
    )
}

export function SidePanelInfoDivider(): JSX.Element {
    return <LemonDivider className="-mx-3 my-2 w-[calc(100%+1rem)]" />
}

export function SidePanelInfoMetaInfo({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="pb-2 flex flex-col gap-2">{children}</div>
}

export function SidePanelInfoCommonActions({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <>
            <div className="flex flex-col gap-2">{children}</div>
            <SidePanelInfoDivider />
        </>
    )
}

export function SidePanelInfoActions({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <Label intent="menu">Actions</Label>
            <div className="flex flex-col gap-px -mx-1.5">{children}</div>
        </div>
    )
}

export function SidePanelTopBarContextActions(): JSX.Element {
    const {
        openInfoPanel,
        openAcessControlTab,
        openDiscussionTab,
        closeInfoPanel,
        closeAcessControlTab,
        closeDiscussionTab,
    } = useActions(sidePanelInfoLogic)
    const {
        sceneHasSidePanel,
        isInfoPanelActuallyOpen,
        isAcessControlPanelActuallyOpen,
        isDiscussionPanelActuallyOpen,
    } = useValues(sidePanelInfoLogic)
    const { setActiveTab } = useActions(sidePanelInfoLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const isDiscussionPanelEnabled = featureFlags[FEATURE_FLAGS.DISCUSSIONS]
    const isInfoPanelActive =
        isInfoPanelActuallyOpen || isAcessControlPanelActuallyOpen || isDiscussionPanelActuallyOpen

    return (
        <div className="flex gap-2">
            <DropdownMenu>
                <DropdownMenuTrigger asChild>
                    <ButtonPrimitive iconOnly active={isInfoPanelActive} tooltip="See available context panels">
                        <IconAdvanced />
                    </ButtonPrimitive>
                </DropdownMenuTrigger>
                <DropdownMenuContent>
                    <DropdownMenuLabel>Context panels</DropdownMenuLabel>
                    <DropdownMenuSeparator />

                    {/* If the scene has a side panel, we show the info panel option */}
                    {sceneHasSidePanel && (
                        <DropdownMenuItem>
                            <ButtonPrimitive
                                menuItem
                                active={isInfoPanelActuallyOpen}
                                onClick={() => {
                                    if (isInfoPanelActuallyOpen) {
                                        closeInfoPanel()
                                    } else {
                                        setActiveTab(SidePanelInfoTab.Info)
                                        openInfoPanel()
                                    }
                                }}
                            >
                                <IconInfo />
                                Info
                            </ButtonPrimitive>
                        </DropdownMenuItem>
                    )}
                    <DropdownMenuItem>
                        <ButtonPrimitive
                            menuItem
                            active={isAcessControlPanelActuallyOpen}
                            onClick={() => {
                                if (isAcessControlPanelActuallyOpen) {
                                    closeAcessControlTab()
                                } else {
                                    setActiveTab(SidePanelInfoTab.AccessControl)
                                    openAcessControlTab()
                                }
                            }}
                        >
                            <IconShieldLock />
                            Access control
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                    {isDiscussionPanelEnabled && (
                        <DropdownMenuItem>
                            <ButtonPrimitive
                                menuItem
                                active={isDiscussionPanelActuallyOpen}
                                onClick={() => {
                                    if (isDiscussionPanelActuallyOpen) {
                                        closeDiscussionTab()
                                    } else {
                                        setActiveTab(SidePanelInfoTab.Discussion)
                                        openDiscussionTab()
                                    }
                                }}
                            >
                                <IconChat />
                                Discussion
                            </ButtonPrimitive>
                        </DropdownMenuItem>
                    )}
                </DropdownMenuContent>
            </DropdownMenu>

            <TopBarSettingsButton buttonProps={{ size: 'xsmall', icon: <IconGear /> }} />
        </div>
    )
}
