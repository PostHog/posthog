import { useActions, useValues } from 'kea'
import { liveEventsSceneLogic } from './liveEventsSceneLogic'

import { Query } from '~/queries/Query/Query'

export function LiveEventsScene(): JSX.Element {
    const { query } = useValues(liveEventsSceneLogic)
    const { setQuery } = useActions(liveEventsSceneLogic)

    return <Query query={query} setQuery={setQuery} context={{ showOpenEditorButton: false }} />
}
