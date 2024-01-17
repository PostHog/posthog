import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { SceneExport } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import { deadLetterQueueLogic, DeadLetterQueueTab } from './deadLetterQueueLogic'
import { MetricsTab } from './MetricsTab'

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
            <PageHeader
                caption={
                    <>
                        <p>
                            Only users with staff access can manage the dead letter queue. Please contact your instance
                            admin.
                        </p>
                        <p>
                            If you're an admin and don't have access, set <code>is_staff=true</code> for your user on
                            the PostgreSQL <code>posthog_user</code> table.
                        </p>
                    </>
                }
            />
        )
    }

    return (
        <div>
            <PageHeader
                caption={
                    <>
                        <p>Manage your instance's dead letter queue.</p>
                    </>
                }
            />

            <LemonTabs
                activeKey={activeTab}
                onChange={(key) => setActiveTab(key as DeadLetterQueueTab)}
                tabs={[{ label: 'Metrics', key: DeadLetterQueueTab.Metrics }]}
            />

            {activeTab === DeadLetterQueueTab.Metrics ? <MetricsTab /> : null}
        </div>
    )
}
