import { useActions, useValues } from 'kea'

import { QueryFeature } from '~/queries/nodes/DataTable/queryFeatures'
import { Query } from '~/queries/Query/Query'

import { eventsSceneLogic } from './eventsSceneLogic'
import { SceneContent, SceneDivider, SceneTitleSection } from '~/layout/scenes/SceneContent'
import { IconApps } from '@posthog/icons'
const RESOURCE_TYPE = 'event'

export function EventsScene(): JSX.Element {
    const { query } = useValues(eventsSceneLogic)
    const { setQuery } = useActions(eventsSceneLogic)

    return (
        <SceneContent>
            <SceneTitleSection
                name="Explore events"
                description="A catalog of all user interactions with your app or website."
                resourceType={{
                    type: RESOURCE_TYPE,
                    typePlural: 'events',
                    forceIcon: <IconApps />,
                }}
            />
            <SceneDivider />
            <Query
                query={query}
                setQuery={setQuery}
                context={{
                    showOpenEditorButton: true,
                    extraDataTableQueryFeatures: [QueryFeature.highlightExceptionEventRows],
                }}
            />
        </SceneContent>
    )
}
