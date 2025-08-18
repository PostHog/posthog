import { useActions, useValues } from 'kea'
import { useCallback, useState } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonInput } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { objectsEqual } from 'lib/utils'

import { ConversionGoalFilter } from '~/queries/schema/schema-general'

import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import { ConversionGoalDropdown } from '../common/ConversionGoalDropdown'
import { defaultConversionGoalFilter } from '../settings/constants'

export const DraftConversionGoalControls = (): JSX.Element => {
    const { setDraftConversionGoal, setConversionGoalInput, resetConversionGoalInput, saveDraftConversionGoal } =
        useActions(marketingAnalyticsLogic)
    const { draftConversionGoal, conversionGoalInput, uniqueConversionGoalName } = useValues(marketingAnalyticsLogic)
    const { addOrUpdateConversionGoal } = useActions(marketingAnalyticsSettingsLogic)

    const [isExpanded, setIsExpanded] = useState<boolean>(false)

    // Dynamic conversion goal handlers
    const handleConversionGoalChange = useCallback(
        (filter: ConversionGoalFilter): void => {
            setConversionGoalInput({
                ...filter,
                conversion_goal_name:
                    conversionGoalInput?.conversion_goal_name || filter.custom_name || filter.name || 'No name',
            })
        },
        [conversionGoalInput?.conversion_goal_name] // oxlint-disable-line react-hooks/exhaustive-deps
    )

    const handleApplyConversionGoal = useCallback((): void => {
        if (conversionGoalInput) {
            setDraftConversionGoal({ ...conversionGoalInput, conversion_goal_name: uniqueConversionGoalName })
            // Keep the input value by updating the local goal with the unique name
            setConversionGoalInput({
                ...conversionGoalInput,
                conversion_goal_name: uniqueConversionGoalName,
            })
        }
    }, [conversionGoalInput, setDraftConversionGoal, setConversionGoalInput, uniqueConversionGoalName])

    const handleSaveConversionGoal = useCallback((): void => {
        addOrUpdateConversionGoal({ ...conversionGoalInput, conversion_goal_name: uniqueConversionGoalName })
        saveDraftConversionGoal()
    }, [conversionGoalInput, addOrUpdateConversionGoal, saveDraftConversionGoal, uniqueConversionGoalName])

    // Check if there are changes to apply
    const hasEvent = conversionGoalInput?.name !== defaultConversionGoalFilter.name
    const hasChanges = conversionGoalInput && !objectsEqual(conversionGoalInput, draftConversionGoal) && hasEvent
    const hasAppliedGoal = !!draftConversionGoal

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
                                value={conversionGoalInput?.conversion_goal_name || ''}
                                onChange={(value) => {
                                    setConversionGoalInput({
                                        ...conversionGoalInput,
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
                                onClick={resetConversionGoalInput}
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
                        value={conversionGoalInput || defaultConversionGoalFilter}
                        onChange={handleConversionGoalChange}
                        typeKey="dynamic-conversion-goal"
                    />
                </>
            )}
        </div>
    )
}
