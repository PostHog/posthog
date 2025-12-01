import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { objectsEqual } from 'lib/utils'
import { urls } from 'scenes/urls'

import { ConversionGoalFilter } from '~/queries/schema/schema-general'

import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { ConversionGoalDropdown } from '../common/ConversionGoalDropdown'
import {
    conversionGoalDescription,
    conversionGoalNamePlaceholder,
    defaultConversionGoalFilter,
    getConfiguredConversionGoalsLabel,
} from '../settings/constants'

export function ConversionGoalModal(): JSX.Element {
    const { conversionGoalModalVisible, draftConversionGoal, conversionGoalInput, conversion_goals } =
        useValues(marketingAnalyticsLogic)
    const {
        hideConversionGoalModal,
        setConversionGoalInput,
        applyConversionGoal,
        saveConversionGoal,
        clearConversionGoal,
        loadConversionGoal,
    } = useActions(marketingAnalyticsLogic)

    const [configuredGoalsExpanded, setConfiguredGoalsExpanded] = useState(false)

    const handleConversionGoalChange = (filter: ConversionGoalFilter): void => {
        setConversionGoalInput({
            ...filter,
            conversion_goal_name:
                conversionGoalInput?.conversion_goal_name || filter.custom_name || filter.name || 'No name',
        })
    }

    const hasEvent = conversionGoalInput?.name !== defaultConversionGoalFilter.name
    const hasChanges = conversionGoalInput && !objectsEqual(conversionGoalInput, draftConversionGoal) && hasEvent
    const hasAppliedGoal = !!draftConversionGoal

    return (
        <LemonModal
            isOpen={conversionGoalModalVisible}
            onClose={hideConversionGoalModal}
            title="Conversion goal"
            width={600}
            footer={
                <div className="flex justify-between items-center w-full">
                    <LemonButton
                        type="secondary"
                        onClick={clearConversionGoal}
                        disabledReason={!hasAppliedGoal ? 'No active goal to clear' : undefined}
                    >
                        Clear
                    </LemonButton>
                    <div className="flex items-center gap-2">
                        <LemonButton
                            type="secondary"
                            onClick={saveConversionGoal}
                            disabledReason={
                                !hasAppliedGoal
                                    ? 'Apply first to verify your conversion goal works correctly'
                                    : undefined
                            }
                        >
                            Save
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={applyConversionGoal}
                            disabledReason={!hasChanges ? 'No changes to apply' : undefined}
                        >
                            Apply
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <div className="space-y-4">
                <p className="text-muted">
                    {conversionGoalDescription}
                    <Link to={urls.settings('environment-marketing-analytics')}>
                        Manage saved conversion goals in settings
                    </Link>
                    .
                </p>

                <div>
                    <label className="text-sm font-medium mb-1 block">Conversion goal name</label>
                    <LemonInput
                        value={conversionGoalInput?.conversion_goal_name || ''}
                        onChange={(value) => {
                            setConversionGoalInput({
                                ...conversionGoalInput,
                                conversion_goal_name: value,
                            })
                        }}
                        placeholder={conversionGoalNamePlaceholder}
                    />
                </div>

                <div>
                    <label className="text-sm font-medium mb-1 block">Event or table</label>
                    <ConversionGoalDropdown
                        key={conversionGoalInput?.conversion_goal_id || 'default'}
                        value={conversionGoalInput || defaultConversionGoalFilter}
                        onChange={handleConversionGoalChange}
                        typeKey="conversion-goal-modal"
                    />
                </div>

                {conversion_goals.length > 0 && (
                    <div className="border rounded">
                        <LemonButton
                            fullWidth
                            type="tertiary"
                            icon={configuredGoalsExpanded ? <IconChevronDown /> : <IconChevronRight />}
                            onClick={() => setConfiguredGoalsExpanded(!configuredGoalsExpanded)}
                            className="justify-start"
                        >
                            {getConfiguredConversionGoalsLabel(conversion_goals.length)}
                        </LemonButton>
                        {configuredGoalsExpanded && (
                            <div className="border-t">
                                {conversion_goals.map((goal) => (
                                    <div
                                        key={goal.conversion_goal_id}
                                        className="flex items-center justify-between px-3 py-2 hover:bg-bg-light cursor-pointer border-b last:border-b-0"
                                        onClick={() => loadConversionGoal(goal)}
                                    >
                                        <div className="flex flex-col">
                                            <span className="font-medium">{goal.conversion_goal_name}</span>
                                            <span className="text-xs text-muted">{goal.custom_name || goal.name}</span>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
