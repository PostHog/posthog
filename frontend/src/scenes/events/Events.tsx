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
            <PageHeader title={'Event explorer'} />
            <div className="non-3000 pt-4 border-t" />
            <EventsScene />
        </>
    )
}
