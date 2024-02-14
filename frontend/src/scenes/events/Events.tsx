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
            <AndroidRecordingsPromptBanner context="events" />
            <EventsScene />
        </>
    )
}
