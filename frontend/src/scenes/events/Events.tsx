import { PageHeader } from 'lib/components/PageHeader'
import { EventsScene } from 'scenes/events/EventsScene'
import { SceneExport } from 'scenes/sceneTypes'

import { eventsSceneLogic } from './eventsSceneLogic'

export const scene: SceneExport = {
    component: Events,
    logic: eventsSceneLogic,
}

export function Events(): JSX.Element {
    return (
        <>
            <PageHeader />
            <EventsScene />
        </>
    )
}
