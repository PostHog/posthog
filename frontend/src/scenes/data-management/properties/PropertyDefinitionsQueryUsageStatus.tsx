import { useActions, useValues } from 'kea'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { propertyDefinitionsTableLogic } from 'scenes/data-management/properties/propertyDefinitionsTableLogic'

export function PropertyDefinitionsQueryUsageStatus(): JSX.Element | null {
    const { showQueryUsage, queryUsageFreshness, queryUsageCoverageDays, usageSortError } =
        useValues(propertyDefinitionsTableLogic)
    const { setFilters } = useActions(propertyDefinitionsTableLogic)

    if (usageSortError) {
        return (
            <LemonBanner
                type="warning"
                action={{
                    children: 'Clear sort',
                    onClick: () => setFilters({ ordering: undefined }, false),
                    'data-attr': 'property-definitions-clear-usage-sort',
                }}
            >
                {usageSortError}
            </LemonBanner>
        )
    }
    if (!showQueryUsage || !queryUsageFreshness) {
        return null
    }
    return (
        <div
            className="flex flex-wrap items-center gap-x-1 text-xs text-secondary"
            data-attr="property-definitions-query-usage-freshness"
        >
            <span>Query counts updated</span>
            <TZLabel time={queryUsageFreshness.computed_at} />
            {queryUsageCoverageDays !== null && (
                <span data-attr="property-definitions-query-usage-coverage">
                    {`· Counts cover only the last ${queryUsageCoverageDays} ${
                        queryUsageCoverageDays === 1 ? 'day' : 'days'
                    }, so a property at 0 may still be in use.`}
                </span>
            )}
        </div>
    )
}
