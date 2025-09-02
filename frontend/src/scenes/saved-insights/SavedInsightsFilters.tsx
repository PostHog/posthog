import { useValues } from 'kea'

import { IconCalendar } from '@posthog/icons'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { MemberSelect } from 'lib/components/MemberSelect'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { cn } from 'lib/utils/css-classes'
import { INSIGHT_TYPE_OPTIONS } from 'scenes/saved-insights/SavedInsights'
import { SavedInsightFilters } from 'scenes/saved-insights/savedInsightsLogic'

import { dashboardsModel } from '~/models/dashboardsModel'
import { SavedInsightsTabs } from '~/types'

export function SavedInsightsFilters({
    filters,
    setFilters,
}: {
    filters: SavedInsightFilters
    setFilters: (filters: Partial<SavedInsightFilters>) => void
}): JSX.Element {
    const { nameSortedDashboards } = useValues(dashboardsModel)
    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')

    const { tab, createdBy, insightType, dateFrom, dateTo, dashboardId, search } = filters

    return (
        <div className={cn('flex justify-between gap-2 mb-2 items-center flex-wrap', newSceneLayout && 'mb-0')}>
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
                        options={INSIGHT_TYPE_OPTIONS}
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
