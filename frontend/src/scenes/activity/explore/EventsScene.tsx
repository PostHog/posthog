import { useActions, useValues } from 'kea'

import { Query } from '~/queries/Query/Query'

import { eventsSceneLogic } from './eventsSceneLogic'

export function EventsScene(): JSX.Element {
    const { query } = useValues(eventsSceneLogic)
    const { setQuery } = useActions(eventsSceneLogic)

    return <Query query={query} setQuery={setQuery} context={{ showOpenEditorButton: true }} />
}
