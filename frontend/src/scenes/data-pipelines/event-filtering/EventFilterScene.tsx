import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { EventFilterForm } from './EventFilterForm'
import { eventFilterLogic } from './eventFilterLogic'

export const scene: SceneExport = {
    component: EventFilterScene,
    logic: eventFilterLogic,
}

export function EventFilterScene(): JSX.Element {
    return (
        <SceneContent>
            <SceneTitleSection
                name="Event ingestion filtering"
                description="Drop events at ingestion time based on event name or distinct ID."
                resourceType={{ type: 'data_pipeline' }}
            />
            <EventFilterForm />
        </SceneContent>
    )
}
