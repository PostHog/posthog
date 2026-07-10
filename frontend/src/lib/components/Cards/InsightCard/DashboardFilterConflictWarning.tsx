import { useValues } from 'kea'

import { IconWarning } from '@posthog/icons'

import { formatPropertyLabel, propertyFilterTypeToPropertyDefinitionType } from 'lib/components/PropertyFilters/utils'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { DashboardFilterConflict } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, GroupPropertyFilter, GroupTypeIndex } from '~/types'

export function DashboardFilterConflictWarning({
    conflicts,
}: {
    conflicts: DashboardFilterConflict[]
}): JSX.Element | null {
    const { cohortsById } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)

    if (!conflicts.length) {
        return null
    }

    const formatFilter = (item: AnyPropertyFilter): string =>
        formatPropertyLabel(
            item,
            cohortsById,
            (s) =>
                formatPropertyValueForDisplay(
                    item.key,
                    s,
                    propertyFilterTypeToPropertyDefinitionType(item.type),
                    (item as GroupPropertyFilter).group_type_index as GroupTypeIndex | undefined
                )?.toString() || '?'
        )

    return (
        <Tooltip
            title={
                <div className="flex flex-col gap-1">
                    <span>
                        Some of this insight's filters contradict this dashboard's filters, so they were ignored and the
                        dashboard's filters were used instead:
                    </span>
                    <ul className="list-disc pl-4">
                        {conflicts.map((conflict, index) => (
                            <li key={index}>
                                "{formatFilter(conflict.insight_filter)}" was replaced by "
                                {formatFilter(conflict.dashboard_filter)}"
                            </li>
                        ))}
                    </ul>
                </div>
            }
        >
            <div className="flex items-center gap-1 text-warning">
                <IconWarning /> Insight filters replaced
            </div>
        </Tooltip>
    )
}
