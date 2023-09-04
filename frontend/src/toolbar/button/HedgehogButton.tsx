import { toolbarButtonLogic } from '~/toolbar/button/toolbarButtonLogic'
import { useActions, useValues } from 'kea'
import { HedgehogActor, HedgehogBuddy } from 'lib/components/HedgehogBuddy/HedgehogBuddy'
import { SPRITE_SIZE } from 'lib/components/HedgehogBuddy/sprites/sprites'
import { toolbarLogic } from '../toolbarLogic'
import { useEffect, useRef } from 'react'
import { heatmapLogic } from '../elements/heatmapLogic'

export function HedgehogButton(): JSX.Element {
    const { hedgehogMode, extensionPercentage, theme } = useValues(toolbarButtonLogic)
    const { saveDragPosition, setExtensionPercentage, setHedgehogActor } = useActions(toolbarButtonLogic)

    const { authenticate } = useActions(toolbarLogic)
    const { isAuthenticated } = useValues(toolbarLogic)

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
    }, [actorRef.current])

    return (
        <>
            {hedgehogMode && (
                <HedgehogBuddy
                    onClose={() => {}}
                    actorRef={actorRef}
                    onClick={() => {
                        if (isAuthenticated) {
                            setExtensionPercentage(extensionPercentage === 1 ? 0 : 1)
                        } else {
                            authenticate()
                        }
                    }}
                    isDarkModeOn={theme === 'dark'}
                    onPositionChange={(actor) => {
                        saveDragPosition(actor.x + SPRITE_SIZE * 0.5, -actor.y - SPRITE_SIZE * 0.5)
                    }}
                />
            )}
        </>
    )
}
