import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { ActivityTab } from '~/types'

export const activityTabs = [
    {
        key: ActivityTab.ExploreEvents,
        label: (
            <span className="flex items-center gap-1">
                {iconForType(sceneConfigurations[Scene.ExploreEvents].iconType)}
                Events
            </span>
        ),
        link: urls.activity(ActivityTab.ExploreEvents),
    },
    {
        key: ActivityTab.ExploreSessions,
        label: (
            <span className="flex items-center gap-1">
                {iconForType(sceneConfigurations[Scene.ExploreSessions].iconType)}
                Sessions
            </span>
        ),
        link: urls.activity(ActivityTab.ExploreSessions),
    },
    {
        key: ActivityTab.LiveEvents,
        label: (
            <span className="flex items-center gap-1">
                {iconForType(sceneConfigurations[Scene.LiveEvents].iconType)}
                Live
            </span>
        ),
        link: urls.activity(ActivityTab.LiveEvents),
    },
]

export const ActivitySceneTabs = ({ activeKey }: { activeKey: ActivityTab }): JSX.Element => {
    return <LemonTabs activeKey={activeKey} tabs={activityTabs} sceneInset className="mb-3" />
}
