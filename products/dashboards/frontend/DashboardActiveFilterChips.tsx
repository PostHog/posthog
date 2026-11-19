import { useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'
import { Badge } from '@posthog/quill'

import { formatPropertyLabel } from 'lib/components/PropertyFilters/utils'
import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { cn } from 'lib/utils/css-classes'
import { dateFilterToText } from 'lib/utils/dateFilters'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { cohortsModel } from '~/models/cohortsModel'
import { getVariableDisplayValue } from '~/queries/nodes/DataVisualization/Components/Variables/variableUtils'
import { getFilterLabel } from '~/taxonomy/helpers'

/** Read-only list of the values in effect, for a bar so narrow that every control sits in the "Filters" menu. */
export function DashboardActiveFilterChips({
    showDateFilter,
    className,
}: {
    showDateFilter: boolean
    className?: string
}): JSX.Element | null {
    const { effectiveEditBarFilters, effectiveVariablesAndAssociatedInsights } = useValues(dashboardLogic)
    const { cohortsById } = useValues(cohortsModel)
    const quillSurface = useQuillSurface()

    const { date_from, date_to, interval, properties, breakdown_filter } = effectiveEditBarFilters
    const breakdowns = (
        breakdown_filter?.breakdowns?.map(({ property }) => property) ??
        (breakdown_filter?.breakdown != null ? [breakdown_filter.breakdown].flat() : [])
    ).map((breakdown) =>
        typeof breakdown === 'number'
            ? (cohortsById[breakdown]?.name ?? `Cohort ${breakdown}`)
            : getFilterLabel(breakdown, TaxonomicFilterGroupType.EventProperties)
    )

    const chips = [
        ...effectiveVariablesAndAssociatedInsights.map(({ variable }) =>
            variable.isNull ? `${variable.name}: null` : `${variable.name}: ${getVariableDisplayValue(variable)}`
        ),
        showDateFilter && (date_from || date_to) ? dateFilterToText(date_from, date_to, null) : null,
        showDateFilter && interval ? `Grouped by ${interval}` : null,
        ...(properties ?? []).map((property) => formatPropertyLabel(property, cohortsById)),
        breakdowns.length ? `Breakdown: ${breakdowns.join(', ')}` : null,
    ].filter((chip): chip is string => !!chip)

    if (!chips.length) {
        return null
    }

    return (
        <ul className={cn('flex min-w-0 flex-wrap gap-1', className)} aria-label="Active filters">
            {chips.map((chip, index) => (
                <li key={index} className="min-w-0 max-w-full">
                    {quillSurface ? (
                        <Badge className="max-w-full truncate">{chip}</Badge>
                    ) : (
                        <LemonTag className="max-w-full truncate">{chip}</LemonTag>
                    )}
                </li>
            ))}
        </ul>
    )
}
