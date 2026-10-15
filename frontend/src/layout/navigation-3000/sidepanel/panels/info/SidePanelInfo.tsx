import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconInfo } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import { sceneLayoutLogic } from '~/layout/scenes/sceneLayoutLogic'
import { SidePanelTab } from '~/types'

import { SidePanelPaneHeader } from '../../components/SidePanelPaneHeader'
import { SidePanelContentContainer } from '../../SidePanelContentContainer'
import { sidePanelLogic } from '../../sidePanelLogic'

export const SidePanelInfoIcon = IconInfo

export function SidePanelInfo(): JSX.Element {
    const { registerScenePanelElement } = useActions(sceneLayoutLogic)
    const { deprecatedTabs } = useValues(sidePanelLogic)
    const ref = useRef<HTMLDivElement>(null)

    useEffect(() => {
        if (ref.current) {
            registerScenePanelElement(ref.current)
        }
        return () => {
            registerScenePanelElement(null)
        }
    }, [registerScenePanelElement])

    return (
        <SidePanelContentContainer>
            <SidePanelPaneHeader title="Actions" />
            {deprecatedTabs.includes(SidePanelTab.Info) && (
                <LemonBanner type="warning" className="mb-2">
                    This panel is going away. Its actions are moving to the menus next to the page title.
                </LemonBanner>
            )}
            <div ref={ref} className="flex flex-col gap-2" />
        </SidePanelContentContainer>
    )
}
