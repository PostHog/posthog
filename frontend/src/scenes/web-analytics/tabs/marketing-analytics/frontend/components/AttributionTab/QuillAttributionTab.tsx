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
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Separator,
    Text,
} from '@posthog/quill'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FilterBar } from 'lib/components/FilterBar'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { ReloadAll } from '~/queries/nodes/DataNode/Reload'
import { MarketingAnalyticsAttributionBreakdown } from '~/queries/schema/schema-general'

import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import {
    MARKETING_ANALYTICS_ATTRIBUTION_COLLECTION_ID,
    marketingAttributionLogic,
    unattributedTooltip,
} from '../../logic/marketingAttributionLogic'
import type { AttributionBreakdownOption } from './AttributionTab'
import { AttributionTable } from './AttributionTable'
import { ConversionPaths } from './ConversionPaths'
import { QuillTabOptionSwitch } from './QuillTabOptionSwitch'

export function QuillAttributionTab({
    settingsUrl,
    noGoalsMessage,
    goalOptions,
    breakdownOptions,
    lookbackOptions,
    onLookbackChange,
}: {
    settingsUrl: string
    noGoalsMessage: string
    goalOptions: { value: string; label: string }[]
    breakdownOptions: AttributionBreakdownOption[]
    lookbackOptions: { value: number; label: string }[]
    onLookbackChange: (value: number) => void
}): JSX.Element {
    const {
        breakdownBy,
        excludeDirectTraffic,
        excludeUnattributed,
        selectedGoalId,
        query,
        pathsQuery,
        effectiveLookbackDays,
        effectiveAllowMultipleConversions,
        optionsOpen,
    } = useValues(marketingAttributionLogic)
    const {
        setBreakdownBy,
        setConversionGoalId,
        setExcludeDirectTraffic,
        setExcludeUnattributed,
        setAllowMultipleConversionsPerVisitor,
        setOptionsOpen,
    } = useActions(marketingAttributionLogic)
    const { dateFilter } = useValues(marketingAnalyticsLogic)
    const { setDates } = useActions(marketingAnalyticsLogic)

    if (!goalOptions.length) {
        return (
            <Item tone="info" size="sm" className="mt-4 flex-wrap">
                <ItemContent>
                    <ItemDescription>{noGoalsMessage}</ItemDescription>
                </ItemContent>
                <ItemActions>
                    <Button variant="outline" nativeButton={false} render={<LinkPrimitive to={settingsUrl} />}>
                        Add a conversion goal
                    </Button>
                </ItemActions>
            </Item>
        )
    }

    return (
        // Rebinds the collection inside the tab, shadowing the scene-level binding on purpose: the
        // refresh button reloads the attribution queries, not the dashboard tiles.
        <BindLogic logic={dataNodeCollectionLogic} props={{ key: MARKETING_ANALYTICS_ATTRIBUTION_COLLECTION_ID }}>
            <div className="flex flex-col">
                <FilterBar
                    showBorderBottom
                    left={
                        <div className="flex flex-wrap items-center gap-4">
                            <div className="flex items-center gap-2">
                                <Text size="xs" variant="muted" render={<span />}>
                                    Conversion goal
                                </Text>
                                <Select<string>
                                    value={selectedGoalId}
                                    onValueChange={(value) => value && setConversionGoalId(value)}
                                >
                                    <SelectTrigger aria-label="Conversion goal">
                                        <SelectValue>
                                            {(selected: string | null) =>
                                                goalOptions.find((option) => option.value === selected)?.label
                                            }
                                        </SelectValue>
                                    </SelectTrigger>
                                    <SelectContent>
                                        {goalOptions.map((option) => (
                                            <SelectItem key={option.value} value={option.value}>
                                                {option.label}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                            <div className="flex items-center gap-2">
                                <Text size="xs" variant="muted" render={<span />}>
                                    Break down by
                                </Text>
                                <Select<MarketingAnalyticsAttributionBreakdown>
                                    value={breakdownBy}
                                    onValueChange={(value) => value && setBreakdownBy(value)}
                                >
                                    <SelectTrigger aria-label="Break down by">
                                        <SelectValue>
                                            {(selected: MarketingAnalyticsAttributionBreakdown | null) =>
                                                breakdownOptions.find((option) => option.value === selected)?.label
                                            }
                                        </SelectValue>
                                    </SelectTrigger>
                                    <SelectContent>
                                        {breakdownOptions.map((option) => (
                                            <SelectItem
                                                key={option.value}
                                                value={option.value}
                                                disabledReason={option.disabledReason}
                                            >
                                                {option.label}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                        </div>
                    }
                    right={
                        <div className="flex flex-wrap items-center gap-2">
                            <ReloadAll iconOnly />
                            <Popover open={optionsOpen} onOpenChange={(open) => setOptionsOpen(open)}>
                                <PopoverTrigger
                                    render={<Button variant="outline" data-attr="marketing-attribution-options" />}
                                >
                                    <IconGear />
                                    Options
                                </PopoverTrigger>
                                <PopoverContent align="end" className="w-80">
                                    <Field>
                                        <FieldLabel>Conversion period</FieldLabel>
                                        <DateFilter
                                            dateFrom={dateFilter.dateFrom}
                                            dateTo={dateFilter.dateTo}
                                            onChange={setDates}
                                        />
                                        <FieldDescription>
                                            Conversions in this period get credited. Their touchpoints can come from
                                            earlier.
                                        </FieldDescription>
                                    </Field>
                                    <Field>
                                        <FieldLabel>Lookback window</FieldLabel>
                                        <Select<number>
                                            value={effectiveLookbackDays}
                                            onValueChange={(value) => value && onLookbackChange(value)}
                                        >
                                            <SelectTrigger aria-label="Lookback window" className="w-full">
                                                <SelectValue>
                                                    {(selected: number | null) =>
                                                        lookbackOptions.find((option) => option.value === selected)
                                                            ?.label
                                                    }
                                                </SelectValue>
                                            </SelectTrigger>
                                            <SelectContent>
                                                {lookbackOptions.map((option) => (
                                                    <SelectItem key={option.value} value={option.value}>
                                                        {option.label}
                                                    </SelectItem>
                                                ))}
                                            </SelectContent>
                                        </Select>
                                        <FieldDescription>
                                            How far back before each conversion a touchpoint can earn credit. The
                                            default comes from your marketing settings.
                                        </FieldDescription>
                                    </Field>
                                    <Separator />
                                    <QuillTabOptionSwitch
                                        checked={excludeDirectTraffic}
                                        onChange={setExcludeDirectTraffic}
                                        label="Exclude direct traffic"
                                        tooltip="Direct sessions stop counting as touchpoints, and the credit they would have taken is shared across the remaining ones."
                                        dataAttr="marketing-attribution-exclude-direct"
                                    />
                                    <QuillTabOptionSwitch
                                        checked={excludeUnattributed}
                                        onChange={setExcludeUnattributed}
                                        label="Exclude unattributed traffic"
                                        tooltip={unattributedTooltip(breakdownBy)}
                                        dataAttr="marketing-attribution-exclude-unattributed"
                                    />
                                    <QuillTabOptionSwitch
                                        checked={effectiveAllowMultipleConversions}
                                        onChange={setAllowMultipleConversionsPerVisitor}
                                        label="Count repeat conversions"
                                        tooltip="Count every conversion a person makes, not just their first. Turning this on can push the rate columns above one conversion per visitor, so they're shown as a ratio instead of a percentage."
                                        dataAttr="marketing-attribution-allow-multiple-conversions"
                                    />
                                </PopoverContent>
                            </Popover>
                        </div>
                    }
                />
                <div className="mt-4 flex flex-col gap-4 pb-8">
                    {query && <AttributionTable query={query} attachTo={marketingAnalyticsLogic} />}
                    {pathsQuery && <ConversionPaths query={pathsQuery} attachTo={marketingAnalyticsLogic} />}
                </div>
            </div>
        </BindLogic>
    )
}
