import { useActions, useValues } from 'kea'
import { useCallback, useState } from 'react'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconChevronDown, IconChevronRight } from '@posthog/icons'

import { ConversionGoalFilter } from '~/queries/schema/schema-general'

import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { ConversionGoalDropdown } from '../common/ConversionGoalDropdown'
import { defaultConversionGoalFilter } from '../settings/constants'

export const DynamicConversionGoalControls = (): JSX.Element => {
    const { setDynamicConversionGoal, clearDynamicConversionGoal } = useActions(marketingAnalyticsLogic)
    const { dynamicConversionGoal } = useValues(marketingAnalyticsLogic)

    const [localConversionGoal, setLocalConversionGoal] = useState<ConversionGoalFilter | null>(null)
    const [isExpanded, setIsExpanded] = useState<boolean>(false)

    // Dynamic conversion goal handlers
    const handleConversionGoalChange = useCallback((filter: ConversionGoalFilter): void => {
        const newGoal: ConversionGoalFilter = {
            ...filter,
            conversion_goal_id: filter.conversion_goal_id || crypto.randomUUID(),
            conversion_goal_name: 'Dynamic Goal',
        }
        setLocalConversionGoal(newGoal)
    }, [])

    const handleApplyConversionGoal = useCallback((): void => {
        setDynamicConversionGoal(localConversionGoal)
    }, [localConversionGoal, setDynamicConversionGoal])

    const handleClearConversionGoal = useCallback((): void => {
        setLocalConversionGoal(null)
        clearDynamicConversionGoal()
    }, [clearDynamicConversionGoal])

    // Check if there are changes to apply
    const hasChanges = JSON.stringify(localConversionGoal) !== JSON.stringify(dynamicConversionGoal)
    const hasActiveGoal = !!dynamicConversionGoal

    return (
        <div className="flex flex-col gap-4">
            <LemonButton
                type="tertiary"
                size="small"
                icon={isExpanded ? <IconChevronDown /> : <IconChevronRight />}
                onClick={() => setIsExpanded(!isExpanded)}
                className="justify-start"
            >
                Try a conversion goal
            </LemonButton>
            {isExpanded && (
                <div className="flex items-center gap-4">
                    <div className="flex-1">
                        <ConversionGoalDropdown
                            value={localConversionGoal || defaultConversionGoalFilter}
                            onChange={handleConversionGoalChange}
                            typeKey="dynamic-conversion-goal"
                        />
                    </div>
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
                            disabledReason={
                                !hasActiveGoal && !localConversionGoal ? 'No active goal to clear' : undefined
                            }
                        >
                            Clear
                        </LemonButton>
                    </div>
                </div>
            )}
        </div>
    )
}
