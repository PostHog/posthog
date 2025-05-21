import { IconCalendar } from '@posthog/icons'
import { useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { MemberSelect } from 'lib/components/MemberSelect'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonSelect, LemonSelectOption, LemonSelectOptionLeaf } from 'lib/lemon-ui/LemonSelect'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { INSIGHT_TYPE_OPTIONS } from 'scenes/saved-insights/SavedInsights'
import { SavedInsightFilters } from 'scenes/saved-insights/savedInsightsLogic'

import { dashboardsModel } from '~/models/dashboardsModel'
import { InsightType, SavedInsightsTabs } from '~/types'

export function SavedInsightsFilters({
    filters,
    setFilters,
}: {
    filters: SavedInsightFilters
    setFilters: (filters: Partial<SavedInsightFilters>) => void
}): JSX.Element {
    const { nameSortedDashboards } = useValues(dashboardsModel)

    const { featureFlags } = useValues(featureFlagLogic)
    const calendarHeatmapInsightEnabled = featureFlags[FEATURE_FLAGS.CALENDAR_HEATMAP_INSIGHT]

    const { tab, createdBy, insightType, dateFrom, dateTo, dashboardId, search } = filters
    const insightTypeOptions = calendarHeatmapInsightEnabled
        ? INSIGHT_TYPE_OPTIONS
        : (INSIGHT_TYPE_OPTIONS as LemonSelectOption<InsightType>[]).filter(
              (option): option is LemonSelectOptionLeaf<InsightType> =>
                  'value' in option && option.value !== InsightType.CALENDAR_HEATMAP
          )

    return (
        <div className="flex justify-between gap-2 mb-2 items-center flex-wrap">
            <LemonInput
                type="search"
                placeholder="Search for insights"
                onChange={(value) => setFilters({ search: value })}
                value={search || ''}
            />
            <div className="flex items-center gap-2 flex-wrap">
                {nameSortedDashboards.length > 0 && (
                    <div className="flex items-center gap-2">
                        <span>On dashboard:</span>
                        <LemonSelect
                            size="small"
                            options={nameSortedDashboards.map((nsd) => ({
                                value: nsd.id,
                                label: nsd.name,
                            }))}
                            value={dashboardId}
                            onChange={(newValue) => {
                                setFilters({ dashboardId: newValue })
                            }}
                            dropdownMatchSelectWidth={false}
                            data-attr="insight-on-dashboard"
                            allowClear={true}
                        />
                    </div>
                )}
                <div className="flex items-center gap-2">
                    <span>Type:</span>
                    <LemonSelect
                        size="small"
                        options={insightTypeOptions}
                        value={insightType}
                        onChange={(v?: string): void => setFilters({ insightType: v })}
                        dropdownMatchSelectWidth={false}
                        data-attr="insight-type"
                    />
                </div>
                <div className="flex items-center gap-2">
                    <span>Last modified:</span>
                    <DateFilter
                        disabled={false}
                        dateFrom={dateFrom}
                        dateTo={dateTo}
                        onChange={(fromDate, toDate) => setFilters({ dateFrom: fromDate, dateTo: toDate ?? undefined })}
                        makeLabel={(key) => (
                            <>
                                <IconCalendar />
                                <span className="hide-when-small"> {key}</span>
                            </>
                        )}
                    />
                </div>
                {tab !== SavedInsightsTabs.Yours ? (
                    <div className="flex items-center gap-2">
                        <span>Created by:</span>
                        <MemberSelect
                            value={createdBy === 'All users' ? null : createdBy}
                            onChange={(user) => setFilters({ createdBy: user?.id || 'All users' })}
                        />
                    </div>
                ) : null}
            </div>
        </div>
    )
}
