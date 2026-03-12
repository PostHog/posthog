import { useActions } from 'kea'
import { useEffect, useRef } from 'react'

import { IconInfo } from '@posthog/icons'

import { sceneLayoutLogic } from '~/layout/scenes/sceneLayoutLogic'

import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'
import { SidePanelContentContainer } from '../SidePanelContentContainer'

export const SidePanelInfoIcon = IconInfo

export function SidePanelInfo(): JSX.Element {
    const { registerScenePanelElement } = useActions(sceneLayoutLogic)
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
            <div ref={ref} className="flex flex-col gap-2" />
        </SidePanelContentContainer>
    )
}
