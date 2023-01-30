import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { CalendarOutlined } from '@ant-design/icons'
import { SavedInsightsTabs } from '~/types'
import { INSIGHT_TYPE_OPTIONS } from 'scenes/saved-insights/SavedInsights'
import { useActions, useValues } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import { membersLogic } from 'scenes/organization/Settings/membersLogic'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'

export function SavedInsightsFilters(): JSX.Element {
    const { nameSortedDashboards } = useValues(dashboardsModel)
    const { setSavedInsightsFilters } = useActions(savedInsightsLogic)
    const { filters } = useValues(savedInsightsLogic)

    const { tab, createdBy, insightType, dateFrom, dateTo, dashboardId, search } = filters

    const { meFirstMembers } = useValues(membersLogic)

    return (
        <div className="flex justify-between gap-2 mb-2 items-center flex-wrap">
            <LemonInput
                type="search"
                placeholder="Search for insights"
                onChange={(value) => setSavedInsightsFilters({ search: value })}
                value={search || ''}
            />
            <div className="flex items-center gap-2 flex-wrap">
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
                                <CalendarOutlined />
                                <span className="hide-when-small"> {key}</span>
                            </>
                        )}
                    />
                </div>
                {tab !== SavedInsightsTabs.Yours ? (
                    <div className="flex items-center gap-2">
                        <span>Created by:</span>
                        {/* TODO: Fix issues with user name order due to numbers having priority */}
                        <LemonSelect
                            size="small"
                            options={[
                                { value: 'All users' as number | 'All users', label: 'All Users' },
                                ...meFirstMembers.map((x) => ({
                                    value: x.user.id,
                                    label: x.user.first_name,
                                })),
                            ]}
                            value={createdBy}
                            onChange={(v: any): void => {
                                setSavedInsightsFilters({ createdBy: v })
                            }}
                            dropdownMatchSelectWidth={false}
                        />
                    </div>
                ) : null}
            </div>
        </div>
    )
}
