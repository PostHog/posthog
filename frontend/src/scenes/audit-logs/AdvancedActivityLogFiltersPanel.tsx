import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonTabs } from '@posthog/lemon-ui'

import { AdvancedFiltersTab } from './AdvancedFiltersTab'
import { BasicFiltersTab } from './BasicFiltersTab'
import { advancedActivityLogsLogic } from './advancedActivityLogsLogic'

export function AdvancedActivityLogFiltersPanel(): JSX.Element {
    const { hasActiveFilters } = useValues(advancedActivityLogsLogic)
    const { clearAllFilters } = useActions(advancedActivityLogsLogic)
    const [activeTab, setActiveTab] = useState<'basic' | 'advanced' | 'hogql'>('basic')

    return (
        <div className="border rounded-lg p-4 bg-bg-light">
            <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold">Filters</h3>
                <div className="flex gap-2">
                    <LemonButton
                        size="small"
                        type="secondary"
                        disabledReason={!hasActiveFilters ? 'No active filters' : undefined}
                        onClick={clearAllFilters}
                        data-attr="audit-logs-clear-filters"
                    >
                        Clear all
                    </LemonButton>
                </div>
            </div>

            <LemonTabs
                activeKey={activeTab}
                onChange={setActiveTab}
                data-attr="audit-logs-filter-tabs"
                tabs={[
                    {
                        key: 'basic',
                        label: 'Basic Filters',
                        content: <BasicFiltersTab />,
                    },
                    {
                        key: 'advanced',
                        label: 'Advanced',
                        content: <AdvancedFiltersTab />,
                    },
                    {
                        key: 'hogql',
                        label: 'HogQL',
                        content: <HogQLFilterTab />,
                    },
                ]}
            />
        </div>
    )
}

const HogQLFilterTab = (): JSX.Element => {
    return (
        <div className="pt-4">
            <div>HogQL filter placeholder</div>
        </div>
    )
}
