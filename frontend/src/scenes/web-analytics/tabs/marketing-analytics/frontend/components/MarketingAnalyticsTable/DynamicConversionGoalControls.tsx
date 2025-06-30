import { useActions, useValues } from 'kea'
import { useCallback, useState } from 'react'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconChevronDown, IconChevronRight } from '@posthog/icons'

import { ConversionGoalFilter } from '~/queries/schema/schema-general'

import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { ConversionGoalDropdown } from '../common/ConversionGoalDropdown'
import { defaultConversionGoalFilter } from '../settings/constants'
import { LemonInput } from '@posthog/lemon-ui'
import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'

export const DynamicConversionGoalControls = (): JSX.Element => {
    const { setDynamicConversionGoal, clearDynamicConversionGoal } = useActions(marketingAnalyticsLogic)
    const { dynamicConversionGoal } = useValues(marketingAnalyticsLogic)
    const { addOrUpdateConversionGoal } = useActions(marketingAnalyticsSettingsLogic)
    const { conversion_goals } = useValues(marketingAnalyticsSettingsLogic)

    const [localConversionGoal, setLocalConversionGoal] = useState<ConversionGoalFilter>({
        ...defaultConversionGoalFilter,
        conversion_goal_id: crypto.randomUUID(),
        conversion_goal_name: '',
    })
    const [localConversionGoalName, setLocalConversionGoalName] = useState<string>('')
    const [isExpanded, setIsExpanded] = useState<boolean>(false)

    // Dynamic conversion goal handlers
    const handleConversionGoalChange = useCallback(
        (filter: ConversionGoalFilter): void => {
            const newGoal: ConversionGoalFilter = {
                ...filter,
                conversion_goal_id: filter.conversion_goal_id,
                conversion_goal_name: localConversionGoalName || filter.custom_name || filter.name || 'No name',
            }
            setLocalConversionGoal(newGoal)
        },
        [localConversionGoal]
    )

    const handleApplyConversionGoal = useCallback((): void => {
        setDynamicConversionGoal(localConversionGoal)
    }, [localConversionGoal, setDynamicConversionGoal])

    const handleSaveConversionGoal = useCallback((): void => {
        addOrUpdateConversionGoal(localConversionGoal)
    }, [localConversionGoal, addOrUpdateConversionGoal])

    const handleClearConversionGoal = useCallback((): void => {
        setLocalConversionGoal({
            ...defaultConversionGoalFilter,
            conversion_goal_name: '',
        })
        clearDynamicConversionGoal()
    }, [clearDynamicConversionGoal])

    // Check if there are changes to apply
    const hasEvent = localConversionGoal.name !== defaultConversionGoalFilter.name
    const hasChanges = JSON.stringify(localConversionGoal) !== JSON.stringify(dynamicConversionGoal) && hasEvent
    const canSave =
        !conversion_goals.some((goal) => goal.conversion_goal_id === localConversionGoal.conversion_goal_id) && hasEvent
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
                Explore conversion goals
            </LemonButton>
            {isExpanded && (
                <>
                    <div className="flex items-center gap-4">
                        <div className="flex gap-2 w-full">
                            <LemonInput
                                className="w-full"
                                value={localConversionGoalName}
                                onChange={(value) => setLocalConversionGoalName(value)}
                                placeholder="e.g., Purchase, Sign Up, Download"
                            />
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={handleApplyConversionGoal}
                                disabledReason={!hasChanges ? 'No changes to apply' : undefined}
                            >
                                Apply
                            </LemonButton>
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={handleClearConversionGoal}
                                disabledReason={!hasActiveGoal ? 'No active goal to clear' : undefined}
                            >
                                Clear
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={handleSaveConversionGoal}
                                disabledReason={!canSave ? 'Goal already exists' : undefined}
                            >
                                Save
                            </LemonButton>
                        </div>
                    </div>
                    <ConversionGoalDropdown
                        value={localConversionGoal || defaultConversionGoalFilter}
                        onChange={handleConversionGoalChange}
                        typeKey="dynamic-conversion-goal"
                    />
                </>
            )}
        </div>
    )
}
