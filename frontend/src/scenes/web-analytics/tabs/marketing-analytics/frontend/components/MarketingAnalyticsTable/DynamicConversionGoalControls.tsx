import { useActions, useValues } from 'kea'
import { useCallback, useRef, useState } from 'react'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconChevronDown, IconChevronRight } from '@posthog/icons'

import { ConversionGoalFilter } from '~/queries/schema/schema-general'
import { objectsEqual, uuid } from 'lib/utils'

import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { ConversionGoalDropdown } from '../common/ConversionGoalDropdown'
import { defaultConversionGoalFilter } from '../settings/constants'
import { LemonInput } from '@posthog/lemon-ui'
import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import { generateUniqueName } from '../../logic/utils'

export const DynamicConversionGoalControls = (): JSX.Element => {
    const { setDynamicConversionGoal } = useActions(marketingAnalyticsLogic)
    const { dynamicConversionGoal } = useValues(marketingAnalyticsLogic)
    const { addOrUpdateConversionGoal } = useActions(marketingAnalyticsSettingsLogic)
    const { conversion_goals } = useValues(marketingAnalyticsSettingsLogic)
    const [localConversionGoalName, setLocalConversionGoalName] = useState<string>('')
    const uniqueName = generateUniqueName(
        localConversionGoalName,
        conversion_goals.map((goal) => goal.conversion_goal_name)
    )

    const conversionGoalIdRef = useRef<string>()
    if (!conversionGoalIdRef.current) {
        conversionGoalIdRef.current = uuid()
    }

    const [localConversionGoal, setLocalConversionGoal] = useState<ConversionGoalFilter>({
        ...defaultConversionGoalFilter,
        conversion_goal_id: conversionGoalIdRef.current,
        conversion_goal_name: '',
    })
    const [isExpanded, setIsExpanded] = useState<boolean>(false)

    // Dynamic conversion goal handlers
    const handleConversionGoalChange = useCallback(
        (filter: ConversionGoalFilter): void => {
            const newGoal: ConversionGoalFilter = {
                ...filter,
                conversion_goal_name: localConversionGoalName || filter.custom_name || filter.name || 'No name',
            }
            setLocalConversionGoal(newGoal)
        },
        [localConversionGoalName]
    )

    const handleApplyConversionGoal = useCallback((): void => {
        setDynamicConversionGoal({ ...localConversionGoal, conversion_goal_name: uniqueName })
        setLocalConversionGoalName(uniqueName)
    }, [localConversionGoal, setDynamicConversionGoal, setLocalConversionGoalName, uniqueName])

    const handleClearConversionGoal = useCallback((): void => {
        conversionGoalIdRef.current = uuid()
        setLocalConversionGoal({
            ...defaultConversionGoalFilter,
            conversion_goal_id: conversionGoalIdRef.current,
            conversion_goal_name: '',
        })
        setLocalConversionGoalName('')
        setDynamicConversionGoal(null)
    }, [setLocalConversionGoalName, setDynamicConversionGoal])

    const handleSaveConversionGoal = useCallback((): void => {
        addOrUpdateConversionGoal({ ...localConversionGoal, conversion_goal_name: uniqueName })
        handleClearConversionGoal()
    }, [localConversionGoal, addOrUpdateConversionGoal, handleClearConversionGoal, uniqueName])

    // Check if there are changes to apply
    const hasEvent = localConversionGoal.name !== defaultConversionGoalFilter.name
    const hasChanges = !objectsEqual(localConversionGoal, dynamicConversionGoal) && hasEvent
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
                                value={localConversionGoalName}
                                onChange={(value) => setLocalConversionGoalName(value)}
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
                                onClick={handleClearConversionGoal}
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
