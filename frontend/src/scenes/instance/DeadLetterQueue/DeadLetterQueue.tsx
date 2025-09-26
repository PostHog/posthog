import { useActions, useValues } from 'kea'

import { IconDatabase } from '@posthog/icons'

import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { SceneExport } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { MetricsTab } from './MetricsTab'
import { DeadLetterQueueTab, deadLetterQueueLogic } from './deadLetterQueueLogic'

export const scene: SceneExport = {
    component: DeadLetterQueue,
    logic: deadLetterQueueLogic,
}

export function DeadLetterQueue(): JSX.Element {
    const { user } = useValues(userLogic)
    const { activeTab } = useValues(deadLetterQueueLogic)
    const { setActiveTab } = useActions(deadLetterQueueLogic)

    if (!user?.is_staff) {
        return (
            <>
                <SceneTitleSection
                    name="Dead Letter Queue"
                    description="Manage your instance's dead letter queue."
                    resourceType={{
                        type: 'dead_letter_queue',
                        forceIcon: <IconDatabase />,
                    }}
                />
                <p>
                    Only users with staff access can manage the dead letter queue. Please contact your instance admin.
                </p>
                <p>
                    If you're an admin and don't have access, set <code>is_staff=true</code> for your user on the
                    PostgreSQL <code>posthog_user</code> table.
                </p>
                <SceneDivider />
            </>
        )
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Dead Letter Queue"
                description="Manage your instance's dead letter queue."
                resourceType={{
                    type: 'dead_letter_queue',
                    forceIcon: <IconDatabase />,
                }}
            />
            <SceneDivider />

            <LemonTabs
                activeKey={activeTab}
                onChange={(key) => setActiveTab(key as DeadLetterQueueTab)}
                tabs={[{ label: 'Metrics', key: DeadLetterQueueTab.Metrics }]}
                sceneInset
            />

            {activeTab === DeadLetterQueueTab.Metrics ? <MetricsTab /> : null}
        </SceneContent>
    )
}
