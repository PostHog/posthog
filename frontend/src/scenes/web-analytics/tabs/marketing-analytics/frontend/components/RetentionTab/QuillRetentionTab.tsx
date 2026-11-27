import { BindLogic, useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import {
    Button,
    Field,
    FieldDescription,
    FieldLabel,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Separator,
    Text,
} from '@posthog/quill'

import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FilterBar } from 'lib/components/FilterBar'
import { closesIntoLemonPopover } from 'lib/components/QuillSurface/closesIntoLemonPopover'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { ReloadAll } from '~/queries/nodes/DataNode/Reload'
import { MarketingAnalyticsAttributionBreakdown } from '~/queries/schema/schema-general'
import { DateMappingOption } from '~/types'

import { RetentionResults } from 'products/marketing_analytics/frontend/retention/RetentionResults'

import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import {
    MARKETING_ANALYTICS_RETENTION_COLLECTION_ID,
    MAX_ACQUISITION_PERIOD_DAYS,
    marketingRetentionLogic,
} from '../../logic/marketingRetentionLogic'
import { QuillOptionSelect } from '../common/QuillOptionSelect'
import { QuillTabOptionSwitch } from '../common/QuillTabOptionSwitch'

export function QuillRetentionTab({
    breakdownOptions,
    dateOptions,
    excludeUnattributedTooltip,
    onUseMaxAcquisitionPeriod,
}: {
    breakdownOptions: { value: MarketingAnalyticsAttributionBreakdown; label: string }[]
    dateOptions: DateMappingOption[]
    excludeUnattributedTooltip: string
    onUseMaxAcquisitionPeriod: () => void
}): JSX.Element {
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

    return (
        // Shadows the scene-level binding on purpose. See MARKETING_ANALYTICS_RETENTION_COLLECTION_ID.
        <BindLogic logic={dataNodeCollectionLogic} props={{ key: MARKETING_ANALYTICS_RETENTION_COLLECTION_ID }}>
            <div className="flex flex-col">
                <FilterBar
                    showBorderBottom
                    left={
                        <div className="flex flex-wrap items-center gap-4">
                            <div className="flex items-center gap-2">
                                <Text size="xs" variant="muted" render={<span />}>
                                    Acquired by
                                </Text>
                                <QuillOptionSelect
                                    value={breakdownBy}
                                    onChange={setBreakdownBy}
                                    options={breakdownOptions}
                                    ariaLabel="Acquired by"
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
                                open={optionsOpen}
                                onOpenChange={(open, details) => {
                                    if (closesIntoLemonPopover(open, details)) {
                                        details.cancel()
                                    } else {
                                        setOptionsOpen(open)
                                    }
                                }}
                            >
                                <PopoverTrigger
                                    render={<Button variant="outline" data-attr="marketing-retention-options" />}
                                >
                                    <IconGear />
                                    Options
                                </PopoverTrigger>
                                <PopoverContent align="end" className="w-80">
                                    <Field>
                                        <FieldLabel>Acquisition period</FieldLabel>
                                        <DateFilter
                                            dateFrom={dateFilter.dateFrom}
                                            dateTo={dateFilter.dateTo}
                                            dateOptions={dateOptions}
                                            showRollingRangePicker={false}
                                            showCustomRangeOptions={false}
                                            onChange={setDates}
                                        />
                                        <FieldDescription>
                                            People acquired in this period are followed for return visits.
                                        </FieldDescription>
                                    </Field>
                                    <Separator />
                                    <QuillTabOptionSwitch
                                        checked={onlyNewUsers}
                                        onChange={setOnlyNewUsers}
                                        label="Only new users"
                                        tooltip="Skip people who had already visited before this period started. Leave it on unless you want a channel's own returning traffic counted as newly acquired."
                                        dataAttr="marketing-retention-only-new-users"
                                    />
                                    <QuillTabOptionSwitch
                                        checked={excludeDirectTraffic}
                                        onChange={setExcludeDirectTraffic}
                                        label="Exclude direct traffic"
                                        tooltip="Direct sessions stop counting when working out where someone came from, so a person's first non-direct session decides their cohort."
                                        dataAttr="marketing-retention-exclude-direct"
                                    />
                                    <QuillTabOptionSwitch
                                        checked={excludeUnattributed}
                                        onChange={setExcludeUnattributed}
                                        label="Exclude unattributed traffic"
                                        tooltip={excludeUnattributedTooltip}
                                        dataAttr="marketing-retention-exclude-unattributed"
                                    />
                                </PopoverContent>
                            </Popover>
                        </div>
                    }
                />
                <div className="mt-4 flex flex-col gap-4 pb-8">
                    {acquisitionPeriodTooLong ? (
                        <Item tone="warning" size="sm" className="flex-wrap">
                            <ItemContent>
                                <ItemDescription>
                                    {`Retention follows people acquired in a period of up to ${MAX_ACQUISITION_PERIOD_DAYS} days. Pick a shorter date range to see the table.`}
                                </ItemDescription>
                            </ItemContent>
                            <ItemActions>
                                <Button variant="outline" onClick={onUseMaxAcquisitionPeriod}>
                                    {`Use the last ${MAX_ACQUISITION_PERIOD_DAYS} days`}
                                </Button>
                            </ItemActions>
                        </Item>
                    ) : (
                        <RetentionResults query={query} attachTo={marketingAnalyticsLogic} />
                    )}
                </div>
            </div>
        </BindLogic>
    )
}
