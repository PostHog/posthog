import { useActions, useValues } from 'kea'
import { hedgehogModeLogic } from 'lib/components/HedgehogMode/hedgehogModeLogic'
import { useEffect } from 'react'

import { toolbarLogic } from '~/toolbar/bar/toolbarLogic'

import { heatmapToolbarMenuLogic } from '../elements/heatmapToolbarMenuLogic'

export function HedgehogButton(): JSX.Element {
    const { hedgehogMode, hedgehogActor } = useValues(toolbarLogic)
    const { syncWithHedgehog, setHedgehogActor, toggleMinimized } = useActions(toolbarLogic)
    const { hedgehogConfig } = useValues(hedgehogModeLogic)
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
            {/* TODO */}
            {/* {hedgehogMode && (
                <HedgehogBuddy
                    hedgehogConfig={hedgehogConfig}
                    onClose={() => {}}
                    onActorLoaded={setHedgehogActor}
                    onPositionChange={() => {
                        syncWithHedgehog()
                    }}
                    onClick={() => toggleMinimized()}
                />
            )} */}
        </>
    )
}
