import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { ActivityTab } from '~/types'

export function useActivityTabs(): {
    key: ActivityTab
    label: string
    link: string
}[] {
    const { featureFlags } = useValues(featureFlagLogic)

    return [
        {
            key: ActivityTab.ExploreEvents,
            label: 'Events',
            link: urls.activity(ActivityTab.ExploreEvents),
        },
        ...(featureFlags[FEATURE_FLAGS.SESSIONS_EXPLORER]
            ? [
                  {
                      key: ActivityTab.ExploreSessions,
                      label: 'Sessions',
                      link: urls.activity(ActivityTab.ExploreSessions),
                  },
              ]
            : []),
        {
            key: ActivityTab.LiveEvents,
            label: 'Live',
            link: urls.activity(ActivityTab.LiveEvents),
        },
    ]
}
