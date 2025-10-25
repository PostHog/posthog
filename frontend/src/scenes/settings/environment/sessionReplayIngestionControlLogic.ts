import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { isObject } from 'lib/utils'
import { variantKeyToIndexFeatureFlagPayloads } from 'scenes/feature-flags/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { FeatureFlagBasicType } from '~/types'

import type { sessionReplayIngestionControlLogicType } from './sessionReplayIngestionControlLogicType'

export const sessionReplayIngestionControlLogic = kea<sessionReplayIngestionControlLogicType>([
    path(['scenes', 'settings', 'project', 'sessionReplayIngestionControlLogic']),
    actions({
        selectFeatureFlag: (flag: FeatureFlagBasicType) => ({ flag }),
    }),
    connect(() => ({ values: [teamLogic, ['currentTeam']], actions: [teamLogic, ['updateCurrentTeam']] })),
    reducers({
        selectedFlag: [
            null as FeatureFlagBasicType | null,
            {
                selectFeatureFlag: (_, { flag }) => flag,
            },
        ],
    }),
    loaders(({ values }) => ({
        featureFlag: {
            loadFeatureFlag: async () => {
                if (values.linkedFeatureFlagId) {
                    const retrievedFlag = await api.featureFlags.get(values.linkedFeatureFlagId)
                    return variantKeyToIndexFeatureFlagPayloads(retrievedFlag)
                }
                return null
            },
        },
    })),
    selectors({
        linkedFeatureFlagId: [
            (s) => [s.currentTeam],
            (currentTeam) => currentTeam?.session_recording_linked_flag?.id || null,
        ],
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
