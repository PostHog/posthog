import { connect, kea, path, reducers, selectors } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sessionReplaySceneLogic } from 'scenes/session-recordings/sessionReplaySceneLogic'

import { ReplayTabs } from '~/types'

import type { replayLandingPageLogicType } from './replayLandingPageLogicType'

/**
 * We want to remember the last replay tab you were on and present that as your current "home" tab
 * Alongside that we want to be able to control which tab we prefer if you've not visited the replay page before
 */
export const replayLandingPageLogic = kea<replayLandingPageLogicType>([
    path(['scenes', 'session-recordings', 'landingPageLogic']),
    connect({ values: [featureFlagLogic, ['featureFlags']], actions: [sessionReplaySceneLogic, ['setTab']] }),
    reducers({
        chosenTab: [
            null as ReplayTabs | null,
            { persist: true },
            {
                setChosenTab: (_, { tab }) => tab,
            },
        ],
    }),
    selectors({
        replayLandingPage: [
            (s) => [s.featureFlags, s.chosenTab],
            (featureFlags, chosenTab): ReplayTabs => {
                if (chosenTab) {
                    // you've already used the product, so we put you back where you left off
                    return chosenTab
                }
                const replayLandingPageFlag = featureFlags[FEATURE_FLAGS.REPLAY_LANDING_PAGE]
                return replayLandingPageFlag === 'templates' ? ReplayTabs.Templates : ReplayTabs.Home
            },
        ],
    }),
])
