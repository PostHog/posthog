import { useActions, useValues } from 'kea'

import { IconDownload } from '@posthog/icons'
import { LemonButton, LemonDropdown } from '@posthog/lemon-ui'

import { ActivityLogSubscribeMenu } from 'lib/components/ActivityLog/ActivityLogSubscribeMenu'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { advancedActivityFiltersToHogProperties } from './advancedActivityFilterTranslation'
import { advancedActivityLogsLogic } from './advancedActivityLogsLogic'
import { BasicFiltersTab } from './BasicFiltersTab'

export function AdvancedActivityLogFiltersPanel(): JSX.Element {
    const { hasActiveFilters, exportsLoading, filters } = useValues(advancedActivityLogsLogic)
    const { clearAllFilters, exportLogs } = useActions(advancedActivityLogsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const { properties: subscribeProperties } = advancedActivityFiltersToHogProperties(filters)

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
                    {featureFlags[FEATURE_FLAGS.CDP_ACTIVITY_LOG_NOTIFICATIONS] && (
                        <ActivityLogSubscribeMenu
                            properties={subscribeProperties}
                            data-attr="audit-logs-subscribe-button"
                        />
                    )}
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

            <BasicFiltersTab />
        </div>
    )
}
