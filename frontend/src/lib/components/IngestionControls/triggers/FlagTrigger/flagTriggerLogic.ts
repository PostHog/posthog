import { actions, afterMount, kea, key, listeners, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { isObject } from 'lib/utils'
import { variantKeyToIndexFeatureFlagPayloads } from 'scenes/feature-flags/featureFlagLogic'

import { LinkedFeatureFlag } from '../../types'
import type { flagTriggerLogicType } from './flagTriggerLogicType'

export type FlagTriggerLogicProps = {
    logicKey: string
    flag: LinkedFeatureFlag | null
    onChange: (flag: LinkedFeatureFlag | null) => void
}

export const flagTriggerLogic = kea<flagTriggerLogicType>([
    props({} as FlagTriggerLogicProps),
    key((props) => props.logicKey),
    path((key) => ['lib', 'components', 'IngestionControls', 'triggers', 'FlagTrigger', 'flagTriggerLogic', key]),
    actions({
        onChange: (flag: LinkedFeatureFlag | null) => ({ flag }),
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
        linkedFeatureFlagId: [(_, p) => [p.flag], (flag) => flag?.id || null],
        flag: [(_, p) => [p.flag], (flag) => flag],
        linkedFlag: [
            (s, p) => [s.featureFlag, p.flag],
            // an existing linked flag is loaded from the API,
            // a newly chosen flag is selected and can be passed in
            // the original value is used to ensure that we don't
            // show stale values as people change the selection
            (featureFlag, flag) => (flag?.id ? featureFlag : null),
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
