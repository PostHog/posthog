import { BindLogic, useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, LemonSelect, LemonSwitch, Popover } from '@posthog/lemon-ui'

import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FilterBar } from 'lib/components/FilterBar'
import { dateMapping } from 'lib/utils/dateFilters'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { ReloadAll } from '~/queries/nodes/DataNode/Reload'
import { MarketingAnalyticsAttributionBreakdown } from '~/queries/schema/schema-general'

import { RetentionResults } from 'products/marketing_analytics/frontend/retention/RetentionResults'

import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { BREAKDOWN_LABELS } from '../../logic/marketingBreakdown'
import {
    MARKETING_ANALYTICS_RETENTION_COLLECTION_ID,
    MAX_ACQUISITION_PERIOD_DAYS,
    marketingRetentionLogic,
} from '../../logic/marketingRetentionLogic'

const RETENTION_DATE_OPTIONS = dateMapping.filter(({ values }) =>
    ['-7d', '-14d', '-30d', '-90d'].includes(values[0] ?? '')
)

export function RetentionTab(): JSX.Element {
    const {
        acquisitionPeriodTooLong,
        breakdownBy,
        excludeDirectTraffic,
        excludeUnattributed,
        onlyNewUsers,
        optionsOpen,
        comparePreviousPeriod,
        query,
    } = useValues(marketingRetentionLogic)
    const {
        setBreakdownBy,
        setExcludeDirectTraffic,
        setExcludeUnattributed,
        setOnlyNewUsers,
        setOptionsOpen,
        setComparePreviousPeriod,
    } = useActions(marketingRetentionLogic)
    const { dateFilter } = useValues(marketingAnalyticsLogic)
    const { setDates } = useActions(marketingAnalyticsLogic)
    const optionsContent = (
        <div className="flex w-80 max-w-[90vw] flex-col gap-4 p-3">
            <div>
                <div className="text-muted mb-2 text-xs font-semibold uppercase">Acquisition period</div>
                <DateFilter
                    dateFrom={dateFilter.dateFrom}
                    dateTo={dateFilter.dateTo}
                    dateOptions={RETENTION_DATE_OPTIONS}
                    showRollingRangePicker={false}
                    showCustomRangeOptions={false}
                    onChange={setDates}
                />
                <div className="text-muted mt-1 text-xs">
                    People acquired in this period are followed for return visits.
                </div>
            </div>
            <LemonDivider className="my-0" />
            <LemonSwitch
                fullWidth
                checked={onlyNewUsers}
                onChange={setOnlyNewUsers}
                label="Only new users"
                tooltip="Skip people who had already visited before this period started. Leave it on unless you want a channel's own returning traffic counted as newly acquired."
                data-attr="marketing-retention-only-new-users"
            />
            <LemonSwitch
                fullWidth
                checked={excludeDirectTraffic}
                onChange={setExcludeDirectTraffic}
                label="Exclude direct traffic"
                tooltip="Direct sessions stop counting when working out where someone came from, so a person's first non-direct session decides their cohort."
                data-attr="marketing-retention-exclude-direct"
            />
            <LemonSwitch
                fullWidth
                checked={excludeUnattributed}
                onChange={setExcludeUnattributed}
                label="Exclude unattributed traffic"
                tooltip={`People whose first session has no ${BREAKDOWN_LABELS[
                    breakdownBy
                ].toLowerCase()} are left out of the table entirely.`}
                data-attr="marketing-retention-exclude-unattributed"
            />
        </div>
    )

    return (
        // Shadows the scene-level binding on purpose. See MARKETING_ANALYTICS_RETENTION_COLLECTION_ID.
        <BindLogic logic={dataNodeCollectionLogic} props={{ key: MARKETING_ANALYTICS_RETENTION_COLLECTION_ID }}>
            <div className="flex flex-col">
                <FilterBar
                    showBorderBottom
                    left={
                        <div className="flex flex-wrap items-center gap-4">
                            <div className="flex items-center gap-2">
                                <span className="text-secondary">Acquired by</span>
                                <LemonSelect
                                    size="small"
                                    value={breakdownBy}
                                    onChange={(value) => value && setBreakdownBy(value)}
                                    options={Object.values(MarketingAnalyticsAttributionBreakdown).map((level) => ({
                                        value: level,
                                        label: BREAKDOWN_LABELS[level],
                                    }))}
                                />
                            </div>
                        </div>
                    }
                    right={
                        <div className="flex flex-wrap items-center gap-2">
                            <CompareFilter
                                compareFilter={{ compare: comparePreviousPeriod }}
                                updateCompareFilter={({ compare }) => setComparePreviousPeriod(!!compare)}
                                allowCustomComparison={false}
                            />
                            <ReloadAll iconOnly />
                            <Popover
                                visible={optionsOpen}
                                onClickOutside={() => setOptionsOpen(false)}
                                placement="bottom-end"
                                overlay={optionsContent}
                            >
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    icon={<IconGear />}
                                    onClick={() => setOptionsOpen(!optionsOpen)}
                                    data-attr="marketing-retention-options"
                                >
                                    Options
                                </LemonButton>
                            </Popover>
                        </div>
                    }
                />
                <div className="mt-4 flex flex-col gap-4 pb-8">
                    {acquisitionPeriodTooLong ? (
                        <LemonBanner
                            type="warning"
                            action={{
                                children: `Use the last ${MAX_ACQUISITION_PERIOD_DAYS} days`,
                                onClick: () => setDates(`-${MAX_ACQUISITION_PERIOD_DAYS}d`, null),
                            }}
                        >
                            Retention follows people acquired in a period of up to {MAX_ACQUISITION_PERIOD_DAYS} days.
                            Pick a shorter date range to see the table.
                        </LemonBanner>
                    ) : (
                        <RetentionResults query={query} attachTo={marketingAnalyticsLogic} />
                    )}
                </div>
            </div>
        </BindLogic>
    )
}
