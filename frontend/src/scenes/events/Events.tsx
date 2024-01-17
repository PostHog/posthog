import { PageHeader } from 'lib/components/PageHeader'
import { EventsScene } from 'scenes/events/EventsScene'
import { SceneExport } from 'scenes/sceneTypes'
import { AndroidRecordingsPromptBanner } from 'scenes/session-recordings/mobile-replay/AndroidRecordingPromptBanner'

import { eventsSceneLogic } from './eventsSceneLogic'

export const scene: SceneExport = {
    component: Events,
    logic: eventsSceneLogic,
}

export function Events(): JSX.Element {
    return (
        <>
            <PageHeader />
            <div className="non-3000 pt-4 border-t" />
            <AndroidRecordingsPromptBanner context="events" />
            <EventsScene />
        </>
    )
}
