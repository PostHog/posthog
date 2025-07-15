import { useActions, useValues } from 'kea'

import { QueryFeature } from '~/queries/nodes/DataTable/queryFeatures'
import { Query } from '~/queries/Query/Query'

import { eventsSceneLogic } from './eventsSceneLogic'

export function EventsScene(): JSX.Element {
    const { query } = useValues(eventsSceneLogic)
    const { setQuery } = useActions(eventsSceneLogic)

    return (
        <Query
            query={query}
            setQuery={setQuery}
            context={{
                showOpenEditorButton: true,
                extraDataTableQueryFeatures: [QueryFeature.highlightExceptionEventRows],
            }}
        />
    )
}
