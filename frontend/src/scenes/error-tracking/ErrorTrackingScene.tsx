import { LemonTable } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

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
                    dataIndex: 'title',
                    width: '50%',
                    render: (_, group) => (
                        <LemonTableLink
                            title={group.title}
                            description={<div className="line-clamp-1">{group.description}</div>}
                            to={urls.errorTrackingGroup(group.id)}
                        />
                    ),
                },
                {
                    title: 'Occurrences',
                    dataIndex: 'occurrences',
                    sorter: (a, b) => a.occurrences - b.occurrences,
                },
                {
                    title: 'Sessions',
                    dataIndex: 'uniqueSessions',
                    sorter: (a, b) => a.uniqueSessions - b.uniqueSessions,
                },
                {
                    title: 'Users',
                    dataIndex: 'uniqueUsers',
                    sorter: (a, b) => a.uniqueUsers - b.uniqueUsers,
                },
            ]}
            loading={errorGroupsLoading}
            dataSource={errorGroups}
        />
    )
}
