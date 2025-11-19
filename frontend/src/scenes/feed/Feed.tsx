import { IconGear, IconNotification } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

export const scene: SceneExport = {
    component: Feed,
}

function FeedPlaceholder(): JSX.Element {
    return (
        <div className="border rounded p-6 bg-surface-primary">
            <div className="space-y-4">
                <div className="h-24 bg-border-light rounded animate-pulse" />
                <div className="h-24 bg-border-light rounded animate-pulse" />
                <div className="h-24 bg-border-light rounded animate-pulse" />
            </div>
            <p className="text-center text-muted mt-4">Feed content will appear here</p>
        </div>
    )
}

function FeedFilters(): JSX.Element {
    return (
        <div className="flex gap-2 items-center">
            <LemonSelect
                placeholder="Filter by type"
                options={[
                    { label: 'All types', value: 'all' },
                    { label: 'Updates', value: 'updates' },
                    { label: 'Changes', value: 'changes' },
                    { label: 'Comments', value: 'comments' },
                ]}
                value="all"
                disabledReason="Coming soon"
            />
            <LemonSelect
                placeholder="Filter by date"
                options={[
                    { label: 'Last 7 days', value: '7d' },
                    { label: 'Last 30 days', value: '30d' },
                    { label: 'Last 90 days', value: '90d' },
                    { label: 'All time', value: 'all' },
                ]}
                value="7d"
                disabledReason="Coming soon"
            />
        </div>
    )
}

export function Feed(): JSX.Element {
    return (
        <SceneContent>
            <SceneTitleSection
                name="Feed"
                description="Stay updated with recent activities and changes in your project"
                resourceType={{
                    type: 'project',
                    forceIcon: <IconNotification />,
                }}
                actions={
                    <>
                        <FeedFilters />
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconGear />}
                            data-attr="feed-preferences"
                            disabledReason="Coming soon"
                        >
                            Preferences
                        </LemonButton>
                    </>
                }
            />
            <FeedPlaceholder />
        </SceneContent>
    )
}
