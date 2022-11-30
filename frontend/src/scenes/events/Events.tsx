import { SceneExport } from 'scenes/sceneTypes'
import { EventsTable } from 'scenes/events/EventsTable'
import { PageHeader } from 'lib/components/PageHeader'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { EventsScene } from 'scenes/events/EventsScene'

export const scene: SceneExport = {
    component: Events,
    // logic: eventsTableLogic,
    // paramsToProps: ({ params: { fixedFilters } }) => ({ fixedFilters, key: 'EventsTable', sceneUrl: urls.events() }),
}

export function Events(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const useDataExploration = featureFlags[FEATURE_FLAGS.DATA_EXPLORATION_LIVE_EVENTS]
    return (
        <>
            <PageHeader title="Live events" caption="Event history limited to the last twelve months." />
            <div className="pt-4 border-t" />
            {useDataExploration ? <EventsScene /> : <EventsTable pageKey={'EventsTable'} />}
        </>
    )
}
