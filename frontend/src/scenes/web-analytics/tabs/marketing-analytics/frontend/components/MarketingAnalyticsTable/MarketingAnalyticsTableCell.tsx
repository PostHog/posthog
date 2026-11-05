import { ComponentProps, createContext, useContext } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import {
    ConversionGoalFilter,
    DataTableNode,
    MARKETING_ANALYTICS_DRILL_DOWN_CONFIG,
    MarketingAnalyticsItem,
    MarketingAnalyticsTableQuery,
} from '~/queries/schema/schema-general'
import { QueryContextColumnComponent } from '~/queries/types'

import {
    ConversionRecordingsSelection,
    conversionRecordingsRequest,
} from 'products/marketing_analytics/frontend/conversionRecordingsRequest'

import { MarketingAnalyticsCell } from '../../shared'

export interface MarketingAnalyticsTableCellOptions {
    conversionGoals: ConversionGoalFilter[]
    tableKey: string
    showConversionRecordings: boolean
    setConversionRecordings: (selection: ConversionRecordingsSelection) => void
}

export const MarketingAnalyticsTableCellContext = createContext<MarketingAnalyticsTableCellOptions | null>(null)

const GROUPING_ALIASES: string[] = Object.values(MARKETING_ANALYTICS_DRILL_DOWN_CONFIG).map((c) => c.columnAlias)

// DataTable mounts each column `render` as a component type, so this must stay one stable module-level
// component. A render function built per render remounts every cell and detaches the old cell DOM.
export function MarketingAnalyticsTableCell(props: ComponentProps<QueryContextColumnComponent>): JSX.Element | null {
    const options = useContext(MarketingAnalyticsTableCellContext)
    const cell = (
        <MarketingAnalyticsCell
            {...props}
            style={{ maxWidth: GROUPING_ALIASES.includes(props.columnName) ? '200px' : undefined }}
        />
    )
    if (!options?.showConversionRecordings) {
        return cell
    }

    const source = (props.query as DataTableNode).source as MarketingAnalyticsTableQuery
    const goals = source.draftConversionGoal
        ? [source.draftConversionGoal, ...options.conversionGoals]
        : options.conversionGoals
    const goal = goals.find((goal) => goal.conversion_goal_name === props.columnName)
    const value = (props.value as MarketingAnalyticsItem | null)?.value
    const request =
        goal && goal.kind !== 'DataWarehouseNode' && typeof value === 'number' && value > 0
            ? conversionRecordingsRequest(source, props.record, goal.conversion_goal_id)
            : null
    if (!goal || !request) {
        return cell
    }

    return (
        <LemonButton
            type="tertiary"
            fullWidth
            className="[&_.cursor-default]:cursor-pointer"
            data-attr="marketing-analytics-conversion-recordings"
            tooltip="View recordings of these conversion sessions"
            onClick={() =>
                options.setConversionRecordings({
                    tableKey: options.tableKey,
                    request,
                    goalName: goal.conversion_goal_name,
                })
            }
        >
            {cell}
        </LemonButton>
    )
}
