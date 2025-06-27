import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { ReloadAll } from '~/queries/nodes/DataNode/Reload'
import { webAnalyticsLogic } from '../../../../../webAnalyticsLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { ConversionGoalFilter } from '~/queries/schema/schema-general'
import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import {
} from '../../../utils'
import { useState } from 'react'
import './MarketingAnalyticsFilters.scss'
import { ConversionGoalDropdown } from '../settings/ConversionGoalDropdown'
import { defaultConversionGoalFilter } from '../settings/constants'
import { uuid } from 'lib/utils'

export const MarketingAnalyticsFilters = (): JSX.Element => {
    const {
        dateFilter: { dateFrom, dateTo },
    } = useValues(webAnalyticsLogic)
    const { setDates } = useActions(webAnalyticsLogic)
    
    const { dynamicConversionGoal } = useValues(marketingAnalyticsLogic)
    const { setDynamicConversionGoal } = useActions(marketingAnalyticsLogic)

    // Local state for the conversion goal being configured
    const [localConversionGoal, setLocalConversionGoal] = useState<ConversionGoalFilter | null>(null)

    const handleConversionGoalChange = (filter: ConversionGoalFilter): void => {
        const newGoal: ConversionGoalFilter = {
            ...filter,
            conversion_goal_id: filter.conversion_goal_id || uuid(),
            conversion_goal_name: 'Dynamic Goal',
        }

        setLocalConversionGoal(newGoal)
    }

    const handleApplyConversionGoal = (): void => {
        setDynamicConversionGoal(localConversionGoal)
    }

    const handleClearConversionGoal = (): void => {
        setLocalConversionGoal(null)
        setDynamicConversionGoal(null)
    }

    // Check if there are changes to apply
    const hasChanges = JSON.stringify(localConversionGoal) !== JSON.stringify(dynamicConversionGoal)
    const hasActiveGoal = !!dynamicConversionGoal

    return (
        <>
        <div className="flex flex-col md:flex-row md:justify-between gap-2">
            <div className="flex flex-col md:flex-row gap-4">
                <ReloadAll />
                
            </div>
            <DateFilter allowTimePrecision dateFrom={dateFrom} dateTo={dateTo} onChange={setDates} />
        </div>
            
        <ConversionGoalDropdown
            value={localConversionGoal || defaultConversionGoalFilter}
            onChange={handleConversionGoalChange}
            typeKey="dynamic-conversion-goal"
        />
        <div className="flex gap-2">
            <LemonButton
                type="primary"
                size="small"
                onClick={handleApplyConversionGoal}
                disabledReason={!localConversionGoal || !hasChanges ? 'No changes to apply' : undefined}
            >
                Apply
            </LemonButton>
            <LemonButton
                type="secondary"
                size="small"
                onClick={handleClearConversionGoal}
                disabledReason={!hasActiveGoal && !localConversionGoal ? 'No active goal to clear' : undefined}
            >
                Clear
            </LemonButton>
            {hasActiveGoal && (
                <span className="text-xs text-muted self-center">
                    Active: {dynamicConversionGoal.conversion_goal_name}
                </span>
            )}
        </div>
    </>
    )
}
