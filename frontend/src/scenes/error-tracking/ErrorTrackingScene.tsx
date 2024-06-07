import { LemonTable } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { EventDetails } from 'scenes/activity/explore/EventDetails'
import { SceneExport } from 'scenes/sceneTypes'

import { ErrorTrackingGroup } from '~/types'

import { errorTrackingSceneLogic } from './errorTrackingSceneLogic'

export const scene: SceneExport = {
    component: ErrorTrackingScene,
    logic: errorTrackingSceneLogic,
}

export function ErrorTrackingScene(): JSX.Element {
    const { errorGroups, errorGroupsLoading } = useValues(errorTrackingSceneLogic)

    return (
        <LemonTable
            columns={[
                {
                    dataIndex: 'message',
                    width: '50%',
                },
                {
                    title: 'Occurrences',
                    dataIndex: 'occurrences',
                    sorter: (a, b) => a.occurrences - b.occurrences,
                },
                {
                    title: 'Sessions',
                    dataIndex: 'unique_sessions',
                    sorter: (a, b) => a.unique_sessions - b.unique_sessions,
                },
            ]}
            loading={errorGroupsLoading}
            dataSource={errorGroups}
            expandable={{
                expandedRowRender: function renderExpand(group: ErrorTrackingGroup) {
                    return <EventDetails event={group.sampleEvent} />
                },
                noIndent: true,
            }}
        />
    )
}
