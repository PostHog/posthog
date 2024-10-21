import { broadcastsLogic } from 'scenes/messaging/broadcastsLogic'
import { MessagingTabs } from 'scenes/messaging/MessagingTabs'
import { SceneExport } from 'scenes/sceneTypes'

export function Broadcasts(): JSX.Element {
    return (
        <>
            <MessagingTabs key="tabs" />
            <div>Broadcasts</div>
        </>
    )
}

export const scene: SceneExport = {
    component: Broadcasts,
    logic: broadcastsLogic,
}
