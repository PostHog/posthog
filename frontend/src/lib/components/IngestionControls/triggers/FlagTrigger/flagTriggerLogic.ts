import { actions, afterMount, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { isObject } from 'lib/utils'
import { variantKeyToIndexFeatureFlagPayloads } from 'scenes/feature-flags/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { TeamType } from '~/types'

import type { flagTriggerLogicType } from './flagTriggerLogicType'

export type FlagTriggerLogicProps = {
    logicKey: string
    flag: TeamType['session_recording_linked_flag'] | null
    onChange: (flag: TeamType['session_recording_linked_flag']) => void
}

export const flagTriggerLogic = kea<flagTriggerLogicType>([
    props({} as FlagTriggerLogicProps),
    key((props) => props.logicKey),
    path((key) => ['lib', 'components', 'IngestionControls', 'triggers', 'FlagTrigger', 'flagTriggerLogic', key]),
    connect(() => ({
        values: [teamLogic, ['currentTeam', 'currentTeamLoading']],
        actions: [teamLogic, ['updateCurrentTeam']],
    })),
    actions({
        onChange: (flag: TeamType['session_recording_linked_flag'] | null) => ({ flag }),
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
        flag: [(s) => [s.currentTeam], (currentTeam) => currentTeam?.session_recording_linked_flag],
        loading: [
            (s) => [s.featureFlagLoading, s.currentTeamLoading],
            (featureFlagLoading, currentTeamLoading) => featureFlagLoading || currentTeamLoading,
        ],
        linkedFeatureFlagId: [
            (s) => [s.currentTeam],
            (currentTeam) => currentTeam?.session_recording_linked_flag?.id || null,
        ],
        linkedFlag: [
            (s) => [s.featureFlag, s.currentTeam],
            // an existing linked flag is loaded from the API,
            // a newly chosen flag is selected and can be passed in
            // the current team is used to ensure that we don't show stale values
            // as people change the selection
            (featureFlag, currentTeam) => (currentTeam?.session_recording_linked_flag?.id ? featureFlag : null),
        ],
        flagHasVariants: [(s) => [s.linkedFlag], (linkedFlag) => isObject(linkedFlag?.filters.multivariate)],
    }),
    listeners(({ props }) => ({
        onChange: ({ flag }) => {
            props.onChange(flag)
        },
    })),
    afterMount(({ actions }) => {
        actions.loadFeatureFlag()
    }),
])
