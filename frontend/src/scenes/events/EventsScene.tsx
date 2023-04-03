import { useActions, useValues } from 'kea'
import { eventsSceneLogic } from 'scenes/events/eventsSceneLogic'
import { Query } from '~/queries/Query/Query'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export function EventsScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const canOpenEditor = !!featureFlags[FEATURE_FLAGS.HOGQL]

    const { query } = useValues(eventsSceneLogic)
    const { setQuery } = useActions(eventsSceneLogic)

    return <Query query={query} setQuery={setQuery} context={{ showOpenEditorButton: canOpenEditor }} />
}
