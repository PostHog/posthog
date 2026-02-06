import { urls } from 'scenes/urls'

import { ActivityTab } from '~/types'

export function useActivityTabs(): {
    key: ActivityTab
    label: string
    link: string
}[] {
    return [
        {
            key: ActivityTab.ExploreEvents,
            label: 'Events',
            link: urls.activity(ActivityTab.ExploreEvents),
        },
        {
            key: ActivityTab.ExploreSessions,
            label: 'Sessions',
            link: urls.activity(ActivityTab.ExploreSessions),
        },
        {
            key: ActivityTab.LiveEvents,
            label: 'Live',
            link: urls.activity(ActivityTab.LiveEvents),
        },
    ]
}
