import { BindLogic, useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonSelect, LemonSwitch, Popover } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FilterBar } from 'lib/components/FilterBar'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { ReloadAll } from '~/queries/nodes/DataNode/Reload'
import {
    MarketingAnalyticsAttributionBreakdown,
    MarketingAnalyticsRetentionInterval,
} from '~/queries/schema/schema-general'

import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { BREAKDOWN_LABELS } from '../../logic/marketingBreakdown'
import {
    MARKETING_ANALYTICS_RETENTION_COLLECTION_ID,
    RETENTION_INTERVAL_LABELS,
    marketingRetentionLogic,
} from '../../logic/marketingRetentionLogic'
import { RetentionCohortTable } from './RetentionCohortTable'

const COLUMN_COUNT_OPTIONS = [4, 6, 8, 12, 16, 24]

export function RetentionTab(): JSX.Element {
    const {
        breakdownBy,
        retentionInterval,
        totalIntervals,
        excludeDirectTraffic,
        excludeUnattributed,
        onlyNewUsers,
        optionsOpen,
        showCohorts,
        comparePreviousPeriod,
        query,
    } = useValues(marketingRetentionLogic)
    const {
        setBreakdownBy,
        setRetentionInterval,
        setTotalIntervals,
        setExcludeDirectTraffic,
        setExcludeUnattributed,
        setOnlyNewUsers,
        setOptionsOpen,
        setShowCohorts,
        setComparePreviousPeriod,
    } = useActions(marketingRetentionLogic)
    const { dateFilter } = useValues(marketingAnalyticsLogic)
    const { setDates } = useActions(marketingAnalyticsLogic)

    const optionsContent = (
        <div className="flex w-80 max-w-[90vw] flex-col gap-4 p-3">
            <div>
                <div className="text-muted mb-2 text-xs font-semibold uppercase">Acquisition period</div>
                <DateFilter dateFrom={dateFilter.dateFrom} dateTo={dateFilter.dateTo} onChange={setDates} />
                <div className="text-muted mt-1 text-xs">
                    People acquired in this period are followed for return visits.
                </div>
            </div>
            {showCohorts && (
                <>
                    <div>
                        <div className="text-muted mb-2 text-xs font-semibold uppercase">Period length</div>
                        <LemonSelect
                            fullWidth
                            value={retentionInterval}
                            onChange={(value) => value && setRetentionInterval(value)}
                            options={Object.values(MarketingAnalyticsRetentionInterval).map((value) => ({
                                value,
                                label: RETENTION_INTERVAL_LABELS[value],
                            }))}
                        />
                    </div>
                    <div>
                        <div className="text-muted mb-2 text-xs font-semibold uppercase">Periods to follow</div>
                        <LemonSelect
                            fullWidth
                            value={totalIntervals}
                            onChange={(value) => value && setTotalIntervals(value)}
                            options={COLUMN_COUNT_OPTIONS.map((count) => ({ value: count, label: `${count} periods` }))}
                        />
                    </div>
                </>
            )}
            {!showCohorts && (
                <LemonSwitch
                    fullWidth
                    checked={comparePreviousPeriod}
                    onChange={setComparePreviousPeriod}
                    label="Compare to previous period"
                />
            )}
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
                            <LemonButton type="secondary" size="small" onClick={() => setShowCohorts(!showCohorts)}>
                                {showCohorts ? 'Back to summary' : 'View cohorts'}
                            </LemonButton>
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
                    <RetentionCohortTable query={query} attachTo={marketingAnalyticsLogic} />
                </div>
            </div>
        </BindLogic>
    )
}
