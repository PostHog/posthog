import { toolbarButtonLogic } from '~/toolbar/bar/toolbarButtonLogic'
import { useActions, useValues } from 'kea'
import { HedgehogActor, HedgehogBuddy } from 'lib/components/HedgehogBuddy/HedgehogBuddy'
import { useEffect, useRef } from 'react'
import { heatmapLogic } from '../elements/heatmapLogic'

export function HedgehogButton(): JSX.Element {
    const { hedgehogMode, theme } = useValues(toolbarButtonLogic)
    const { syncWithHedgehog, setHedgehogActor, toggleMinimized } = useActions(toolbarButtonLogic)

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
                    isDarkModeOn={theme === 'dark'}
                    onPositionChange={() => {
                        syncWithHedgehog()
                    }}
                    onClick={() => toggleMinimized()}
                />
            )}
        </>
    )
}
