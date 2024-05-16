import { useActions, useValues } from 'kea'
import { HedgehogBuddy } from 'lib/components/HedgehogBuddy/HedgehogBuddy'
import { useEffect } from 'react'

import { toolbarLogic } from '~/toolbar/bar/toolbarLogic'

import { heatmapLogic } from '../elements/heatmapLogic'

export function HedgehogButton(): JSX.Element {
    const { hedgehogMode, hedgehogActor } = useValues(toolbarLogic)
    const { syncWithHedgehog, setHedgehogActor, toggleMinimized } = useActions(toolbarLogic)

    const { heatmapEnabled } = useValues(heatmapLogic)

    useEffect(() => {
        if (heatmapEnabled) {
            hedgehogActor?.setAnimation('heatmaps')
        }
    }, [heatmapEnabled])

    return (
        <>
            {hedgehogMode && (
                <HedgehogBuddy
                    onClose={() => {}}
                    onActorLoaded={setHedgehogActor}
                    onPositionChange={() => {
                        syncWithHedgehog()
                    }}
                    onClick={() => toggleMinimized()}
                />
            )}
        </>
    )
}
