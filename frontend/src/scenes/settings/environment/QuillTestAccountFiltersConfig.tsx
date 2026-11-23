import { Item, ItemContent, ItemDescription, Text } from '@posthog/quill'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { QuillSurfaceContext } from 'lib/ui/QuillSurface/quillSurfaceContext'
import { FrequentMistakeAdvice } from 'scenes/teamLogic'

import { AnyPropertyFilter } from '~/types'

import { QuillSettingSwitch } from '../components/QuillSettingSwitch'
import { ApplyTestAccountFilterToExistingInsights } from './ApplyTestAccountFilterToExistingInsights'

export function QuillTestAccountFiltersConfig({
    filters,
    showFilters,
    warningLabels,
    frequentMistakes,
    taxonomicGroupTypes,
    restrictedReason,
    loading,
    defaultChecked,
    filterRevenueAnalytics,
    onFiltersChange,
    onDefaultCheckedChange,
    onFilterRevenueAnalyticsChange,
}: {
    filters: AnyPropertyFilter[] | undefined
    showFilters: boolean
    warningLabels: string[] | null
    frequentMistakes: FrequentMistakeAdvice[]
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
    restrictedReason: string | null
    loading: boolean
    defaultChecked: boolean
    filterRevenueAnalytics: boolean
    onFiltersChange: (filters: AnyPropertyFilter[]) => void
    onDefaultCheckedChange: (checked: boolean) => void
    onFilterRevenueAnalyticsChange: (checked: boolean) => void
}): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
                <Item tone="info" size="sm">
                    <ItemContent>
                        <ItemDescription>
                            When filtering out internal users, inline person property filters (e.g., "email does not
                            contain your-domain.com") work everywhere, including real-time CDP destinations.
                            Alternatively, you can create a cohort and add it with a "not in" operator - this works well
                            for analytics queries (insights, dashboards) and also works in CDP destinations if the
                            cohort contains <strong>exclusively person property filters</strong>. Cohorts with
                            behavioral filters or no properties defined will cause CDP destinations to error.
                        </ItemDescription>
                    </ItemContent>
                </Item>
                {!!warningLabels && warningLabels.length > 0 && (
                    <Item tone="warning" size="sm">
                        <ItemContent>
                            <Text size="xs" render={<p className="m-0" />}>
                                You've added an <strong>inclusive</strong> filter. It keeps only the matching events and
                                removes everything else, also in destinations that use this filter. To remove internal
                                users, use an <strong>exclusive</strong> operator such as <i>does not contain</i>.
                            </Text>
                            <Text size="xs" render={<p className="m-0" />}>
                                Inclusive filters are currently set for the following properties:
                            </Text>
                            <ul className="m-0 list-disc ps-4 text-xs">
                                {warningLabels.map((label, index) => (
                                    <li key={index}>{label}</li>
                                ))}
                            </ul>
                        </ItemContent>
                    </Item>
                )}
                {frequentMistakes.length > 0 && (
                    <Item tone="warning" size="sm">
                        <ItemContent>
                            <Text size="xs" render={<p className="m-0" />}>
                                Your filter contains a setting that is likely to exclude or include unexpected users.
                            </Text>
                            <ul className="m-0 list-disc ps-4 text-xs">
                                {frequentMistakes.map(({ key, type, fix }, index) => (
                                    <li key={index}>
                                        {key} is a {type} property, but {fix}.
                                    </li>
                                ))}
                            </ul>
                        </ItemContent>
                    </Item>
                )}
                {showFilters && (
                    <QuillSurfaceContext.Provider value={true}>
                        <PropertyFilters
                            pageKey="testaccountfilters"
                            propertyFilters={filters}
                            onChange={onFiltersChange}
                            taxonomicGroupTypes={taxonomicGroupTypes}
                            disabledReason={restrictedReason ?? undefined}
                        />
                    </QuillSurfaceContext.Provider>
                )}
            </div>
            <div className="flex flex-col gap-2">
                <QuillSettingSwitch
                    label="Enable this filter on all new insights"
                    checked={defaultChecked}
                    onCheckedChange={onDefaultCheckedChange}
                    disabled={loading}
                    disabledReason={restrictedReason}
                />
                <QuillSettingSwitch
                    label="Filter out internal and test users from revenue analytics"
                    checked={filterRevenueAnalytics}
                    onCheckedChange={onFilterRevenueAnalyticsChange}
                    disabled={loading}
                    disabledReason={restrictedReason}
                />
            </div>
            <ApplyTestAccountFilterToExistingInsights />
        </div>
    )
}
