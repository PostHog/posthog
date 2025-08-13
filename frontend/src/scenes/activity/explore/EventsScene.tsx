import { useActions, useValues } from 'kea'

import { QueryFeature } from '~/queries/nodes/DataTable/queryFeatures'
import { Query } from '~/queries/Query/Query'

import { eventsSceneLogic } from './eventsSceneLogic'
import { activitySceneLogic } from 'scenes/activity/activitySceneLogic'
import { useAttachedLogic } from 'lib/logic/scene-plugin/useAttachedLogic'

export function EventsScene({ tabId }: { tabId: string }): JSX.Element {
    const { query } = useValues(eventsSceneLogic({ tabId }))
    const { setQuery } = useActions(eventsSceneLogic({ tabId }))

    useAttachedLogic(eventsSceneLogic({ tabId }), activitySceneLogic)

    return (
        <Query
            attachTo={eventsSceneLogic({ tabId })}
            uniqueKey={`events-scene-${tabId}`}
            query={query}
            setQuery={setQuery}
            context={{
                showOpenEditorButton: true,
                extraDataTableQueryFeatures: [QueryFeature.highlightExceptionEventRows],
            }}
        />
    )
}
