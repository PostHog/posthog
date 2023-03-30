import { toolbarButtonLogic } from '~/toolbar/button/toolbarButtonLogic'
import { useActions, useValues } from 'kea'
import { HedgehogActor, HedgehogBuddy } from 'lib/components/HedgehogBuddy/HedgehogBuddy'
import { SPRITE_SIZE } from 'lib/components/HedgehogBuddy/sprites/sprites'
import { toolbarLogic } from '../toolbarLogic'
import { useEffect, useRef } from 'react'
import { heatmapLogic } from '../elements/heatmapLogic'

export function HedgehogButton(): JSX.Element {
    const { hedgehogMode, extensionPercentage } = useValues(toolbarButtonLogic)
    const { saveDragPosition, setExtensionPercentage } = useActions(toolbarButtonLogic)

    const { authenticate } = useActions(toolbarLogic)
    const { isAuthenticated } = useValues(toolbarLogic)

    const { heatmapEnabled } = useValues(heatmapLogic)

    const actorRef = useRef<HedgehogActor>()

    useEffect(() => {
        if (heatmapEnabled) {
            // TODO: Change to fire
            actorRef.current?.setAnimation('spin')
        }
    }, [heatmapEnabled])

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
                    onPositionChange={(actor) => {
                        saveDragPosition(actor.x + SPRITE_SIZE * 0.5, -actor.y - SPRITE_SIZE * 0.5)
                    }}
                />
            )}
        </>
    )
}
