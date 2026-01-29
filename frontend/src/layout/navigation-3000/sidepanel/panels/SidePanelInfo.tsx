import { useActions } from 'kea'
import { useEffect, useRef } from 'react'

import { IconInfo } from '@posthog/icons'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'

import { sceneLayoutLogic } from '~/layout/scenes/sceneLayoutLogic'

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
        <ScrollableShadows direction="vertical" className="grow flex-1" innerClassName="px-2 py-2" styledScrollbars>
            <div ref={ref} className="flex flex-col gap-2" />
        </ScrollableShadows>
    )
}
