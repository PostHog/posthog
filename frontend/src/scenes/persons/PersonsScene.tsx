import { SceneExport } from 'scenes/sceneTypes'
import { useValues } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema'
import { Persons } from 'scenes/persons/Persons'
import { PersonPageHeader } from 'scenes/persons/PersonPageHeader'

export const scene: SceneExport = {
    component: PersonsScene,
}

export function PersonsScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const featureDataExploration = featureFlags[FEATURE_FLAGS.DATA_EXPLORATION_LIVE_EVENTS]
    return (
        <>
            <PersonPageHeader />
            {featureDataExploration ? (
                <Query
                    query={{
                        kind: NodeKind.DataTableNode,
                        source: { kind: NodeKind.PersonsNode },
                        columns: [
                            'person',
                            'id',
                            'created_at',
                            'properties.$geoip_country_name',
                            'properties.$browser',
                        ],
                        propertiesViaUrl: true,
                        showSearch: true,
                        showPropertyFilter: true,
                        showExport: true,
                        showReload: true,
                    }}
                    setQueryLocally
                />
            ) : (
                <Persons />
            )}
        </>
    )
}
