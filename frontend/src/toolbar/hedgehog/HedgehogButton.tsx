import { useActions, useValues } from 'kea'
import { HedgehogBuddy } from 'lib/components/HedgehogBuddy/HedgehogBuddy'
import { hedgehogBuddyLogic } from 'lib/components/HedgehogBuddy/hedgehogBuddyLogic'
import { useEffect } from 'react'

import { toolbarLogic } from '~/toolbar/bar/toolbarLogic'

import { heatmapToolbarMenuLogic } from '../elements/heatmapToolbarMenuLogic'

export function HedgehogButton(): JSX.Element {
    const { hedgehogMode, hedgehogActor } = useValues(toolbarLogic)
    const { syncWithHedgehog, setHedgehogActor, toggleMinimized } = useActions(toolbarLogic)
    const { hedgehogConfig } = useValues(hedgehogBuddyLogic)
    const { heatmapEnabled } = useValues(heatmapToolbarMenuLogic)

    useEffect(() => {
        if (heatmapEnabled) {
            hedgehogActor?.setOnFire(1)
        }
    }, [heatmapEnabled])

    useEffect(() => {
        return hedgehogActor?.setupKeyboardListeners()
    }, [hedgehogActor])

    return (
        <>
            {hedgehogMode && (
                <HedgehogBuddy
                    hedgehogConfig={hedgehogConfig}
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
