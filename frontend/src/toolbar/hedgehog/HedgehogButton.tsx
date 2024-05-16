import { useActions, useValues } from 'kea'
import { HedgehogActor, HedgehogBuddy } from 'lib/components/HedgehogBuddy/HedgehogBuddy'
import { useEffect, useRef } from 'react'

import { toolbarLogic } from '~/toolbar/bar/toolbarLogic'

import { heatmapLogic } from '../elements/heatmapLogic'

export function HedgehogButton(): JSX.Element {
    const { hedgehogMode } = useValues(toolbarLogic)
    const { syncWithHedgehog, setHedgehogActor, toggleMinimized } = useActions(toolbarLogic)

    const { heatmapEnabled } = useValues(heatmapLogic)

    const actorRef = useRef<HedgehogActor>()

    useEffect(() => {
        if (heatmapEnabled) {
            actorRef.current?.setAnimation('heatmaps')
        }
    }, [heatmapEnabled])

    useEffect(() => {
        if (actorRef.current) {
            setHedgehogActor(actorRef.current)
        }
    }, [actorRef.current, hedgehogMode])

    return (
        <>
            {hedgehogMode && (
                <HedgehogBuddy
                    onClose={() => {}}
                    actorRef={actorRef}
                    onPositionChange={() => {
                        syncWithHedgehog()
                    }}
                    onClick={() => toggleMinimized()}
                />
            )}
        </>
    )
}
