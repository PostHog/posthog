import { useActions, useValues } from 'kea'
import { useCallback, useState } from 'react'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconChevronDown, IconChevronRight } from '@posthog/icons'

import { ConversionGoalFilter } from '~/queries/schema/schema-general'
import { objectsEqual } from 'lib/utils'

import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { ConversionGoalDropdown } from '../common/ConversionGoalDropdown'
import { defaultConversionGoalFilter } from '../settings/constants'
import { LemonInput } from '@posthog/lemon-ui'
import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'

export const DynamicConversionGoalControls = (): JSX.Element => {
    const { setDynamicConversionGoal, setLocalConversionGoal, resetLocalConversionGoal, saveDynamicConversionGoal } =
        useActions(marketingAnalyticsLogic)
    const { dynamicConversionGoal, localConversionGoal, uniqueConversionGoalName } = useValues(marketingAnalyticsLogic)
    const { addOrUpdateConversionGoal } = useActions(marketingAnalyticsSettingsLogic)

    const [isExpanded, setIsExpanded] = useState<boolean>(false)

    // Dynamic conversion goal handlers
    const handleConversionGoalChange = useCallback(
        (filter: ConversionGoalFilter): void => {
            setLocalConversionGoal({
                ...filter,
                conversion_goal_name:
                    localConversionGoal?.conversion_goal_name || filter.custom_name || filter.name || 'No name',
            })
        },
        [localConversionGoal?.conversion_goal_name]
    )

    const handleApplyConversionGoal = useCallback((): void => {
        if (localConversionGoal) {
            setDynamicConversionGoal({ ...localConversionGoal, conversion_goal_name: uniqueConversionGoalName })
            // Keep the input value by updating the local goal with the unique name
            setLocalConversionGoal({
                ...localConversionGoal,
                conversion_goal_name: uniqueConversionGoalName,
            })
        }
    }, [localConversionGoal, setDynamicConversionGoal, setLocalConversionGoal, uniqueConversionGoalName])

    const handleSaveConversionGoal = useCallback((): void => {
        addOrUpdateConversionGoal({ ...localConversionGoal, conversion_goal_name: uniqueConversionGoalName })
        saveDynamicConversionGoal()
    }, [localConversionGoal, addOrUpdateConversionGoal, saveDynamicConversionGoal, uniqueConversionGoalName])

    // Check if there are changes to apply
    const hasEvent = localConversionGoal?.name !== defaultConversionGoalFilter.name
    const hasChanges = localConversionGoal && !objectsEqual(localConversionGoal, dynamicConversionGoal) && hasEvent
    const hasAppliedGoal = !!dynamicConversionGoal

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
                                value={localConversionGoal?.conversion_goal_name || ''}
                                onChange={(value) => {
                                    setLocalConversionGoal({
                                        ...localConversionGoal,
                                        conversion_goal_name: value,
                                    })
                                }}
                                placeholder="Conversion goal name, e.g. purchase, sign up, download"
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
                                onClick={resetLocalConversionGoal}
                                disabledReason={!hasAppliedGoal ? 'No active goal to clear' : undefined}
                            >
                                Clear
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={handleSaveConversionGoal}
                                disabledReason={
                                    !hasAppliedGoal ? 'You need to apply a conversion goal first' : undefined
                                }
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
