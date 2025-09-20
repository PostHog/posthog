import { actions, afterMount, connect, kea, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { isObject } from 'lib/utils'
import { variantKeyToIndexFeatureFlagPayloads } from 'scenes/feature-flags/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { FeatureFlagBasicType } from '~/types'

import type { sessionReplayLinkedFlagLogicType } from './sessionReplayLinkedFlagLogicType'

export interface ReplayLinkedFlagLogicProps {
    id: number | null
}

export const sessionReplayLinkedFlagLogic = kea<sessionReplayLinkedFlagLogicType>([
    path(['scenes', 'settings', 'project', 'sessionReplayLinkedFlagLogic']),
    actions({
        selectFeatureFlag: (flag: FeatureFlagBasicType) => ({ flag }),
    }),
    connect(() => ({ values: [teamLogic, ['currentTeam']] })),
    reducers({
        selectedFlag: [
            null as FeatureFlagBasicType | null,
            {
                selectFeatureFlag: (_, { flag }) => flag,
            },
        ],
    }),
    props({} as ReplayLinkedFlagLogicProps),
    loaders(({ props }) => ({
        featureFlag: {
            loadFeatureFlag: async () => {
                if (props.id) {
                    const retrievedFlag = await api.featureFlags.get(props.id)
                    return variantKeyToIndexFeatureFlagPayloads(retrievedFlag)
                }
                return null
            },
        },
    })),
    selectors({
        linkedFlag: [
            (s) => [s.featureFlag, s.selectedFlag, s.currentTeam],
            // an existing linked flag is loaded from the API,
            // a newly chosen flag is selected can be passed in
            // the current team is used to ensure that we don't show stale values
            // as people change the selection
            (featureFlag, selectedFlag, currentTeam) =>
                currentTeam?.session_recording_linked_flag?.id ? selectedFlag || featureFlag : null,
        ],
        flagHasVariants: [(s) => [s.linkedFlag], (linkedFlag) => isObject(linkedFlag?.filters.multivariate)],
    }),
    afterMount(({ actions }) => {
        actions.loadFeatureFlag()
    }),
])
