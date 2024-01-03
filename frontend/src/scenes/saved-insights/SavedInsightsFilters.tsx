import { IconCalendar } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { MemberSelect } from 'lib/components/MemberSelect'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { INSIGHT_TYPE_OPTIONS } from 'scenes/saved-insights/SavedInsights'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'

import { dashboardsModel } from '~/models/dashboardsModel'
import { SavedInsightsTabs } from '~/types'

export function SavedInsightsFilters(): JSX.Element {
    const { nameSortedDashboards } = useValues(dashboardsModel)
    const { setSavedInsightsFilters } = useActions(savedInsightsLogic)
    const { filters } = useValues(savedInsightsLogic)

    const { tab, createdBy, insightType, dateFrom, dateTo, dashboardId, search } = filters

    return (
        <div className="flex justify-between gap-2 mb-2 items-center flex-wrap">
            <LemonInput
                type="search"
                placeholder="Search for insights"
                onChange={(value) => setSavedInsightsFilters({ search: value })}
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
                                setSavedInsightsFilters({ dashboardId: newValue })
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
                        onChange={(v: any): void => setSavedInsightsFilters({ insightType: v })}
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
                        onChange={(fromDate, toDate) =>
                            setSavedInsightsFilters({ dateFrom: fromDate, dateTo: toDate ?? undefined })
                        }
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
                            onChange={(user) => setSavedInsightsFilters({ createdBy: user?.id || 'All users' })}
                        />
                    </div>
                ) : null}
            </div>
        </div>
    )
}
