import { useActions, useValues } from 'kea'

import { LemonTabs } from '@posthog/lemon-ui'

import { DataDeletionHistory } from './DataDeletionHistory'
import { dataDeletionLogic } from './dataDeletionLogic'
import { DataDeletionNewRequest } from './DataDeletionNewRequest'

export function DataDeletion(): JSX.Element {
    const { activeTab, activeCount } = useValues(dataDeletionLogic)
    const { setActiveTab } = useActions(dataDeletionLogic)

    return (
        <div className="flex flex-col gap-4">
            <LemonTabs
                activeKey={activeTab}
                onChange={(key) => setActiveTab(key)}
                tabs={[
                    {
                        key: 'new',
                        label: 'New request',
                        content: <DataDeletionNewRequest />,
                    },
                    {
                        key: 'history',
                        label: activeCount > 0 ? `History (${activeCount} active)` : 'History',
                        content: <DataDeletionHistory />,
                    },
                ]}
            />
        </div>
    )
}
