import { kea, connect, path, actions, reducers, selectors, afterMount } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import type { searchButtonLogicType } from './searchButtonLogicType'

export const searchButtonLogic = kea<searchButtonLogicType>([
    path(['lib', 'components', 'NavSearchButton', 'searchButtonLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),
    actions(() => ({
        hideHint: true,
    })),
    reducers(() => ({
        hintVisible: [
            true,
            {
                hideHint: () => false,
            },
        ],
    })),
    selectors(() => ({
        isHintEnabled: [
            (s) => [s.featureFlags],
            (featureFlags) => featureFlags[FEATURE_FLAGS.SIDEBAR_SEARCH_COMMAND_HINT] === 'test',
        ],
        showHint: [
            (s) => [s.hintVisible, s.isHintEnabled],
            (hintVisible, isHintEnabled) => hintVisible && isHintEnabled,
        ],
    })),
    afterMount(({ actions, cache }) => {
        cache.disposables.add(() => {
            const id = setTimeout(() => actions.hideHint(), 5000)

            return () => clearTimeout(id)
        }, 'hintTimer')
    }),
])
