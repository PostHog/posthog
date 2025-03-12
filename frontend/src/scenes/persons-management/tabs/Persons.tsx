import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { personsSceneLogic } from 'scenes/persons-management/tabs/personsSceneLogic'

import { Query } from '~/queries/Query/Query'

export function Persons(): JSX.Element {
    const { query } = useValues(personsSceneLogic)
    const { setQuery } = useActions(personsSceneLogic)

    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <Query
            query={query}
            setQuery={setQuery}
            context={{ refresh: featureFlags[FEATURE_FLAGS.CRM_BLOCKING_QUERIES] === 'test' ? 'blocking' : true }}
            dataAttr="persons-table"
        />
    )
}
