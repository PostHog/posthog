import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconDownload } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonTabs } from '@posthog/lemon-ui'

import { AdvancedFiltersTab } from './AdvancedFiltersTab'
import { BasicFiltersTab } from './BasicFiltersTab'
import { advancedActivityLogsLogic } from './advancedActivityLogsLogic'

export function AdvancedActivityLogFiltersPanel(): JSX.Element {
    const { hasActiveFilters, exportsLoading } = useValues(advancedActivityLogsLogic)
    const { clearAllFilters, exportLogs } = useActions(advancedActivityLogsLogic)
    const [activeTab, setActiveTab] = useState<'basic' | 'advanced' | 'hogql'>('basic')

    return (
        <div className="border rounded-md p-4 bg-bg-light">
            <div className="flex items-center justify-end">
                <div className="flex gap-2">
                    <LemonDropdown
                        overlay={
                            <div className="space-y-1 p-1">
                                <LemonButton
                                    size="small"
                                    fullWidth
                                    onClick={() => exportLogs('csv')}
                                    loading={exportsLoading}
                                    data-attr="audit-logs-export-csv"
                                >
                                    Export as CSV
                                </LemonButton>
                                <LemonButton
                                    size="small"
                                    fullWidth
                                    onClick={() => exportLogs('xlsx')}
                                    loading={exportsLoading}
                                    data-attr="audit-logs-export-xlsx"
                                >
                                    Export as Excel
                                </LemonButton>
                            </div>
                        }
                        placement="bottom-end"
                        data-attr="audit-logs-export-dropdown"
                    >
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconDownload />}
                            data-attr="audit-logs-export-button"
                        >
                            Export
                        </LemonButton>
                    </LemonDropdown>
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
                        label: 'Filters',
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
