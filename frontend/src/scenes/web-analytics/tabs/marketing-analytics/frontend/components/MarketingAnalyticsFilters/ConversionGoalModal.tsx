import { useActions, useValues } from 'kea'
import { useCallback, useState } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { objectsEqual } from 'lib/utils'
import { urls } from 'scenes/urls'

import { ConversionGoalFilter } from '~/queries/schema/schema-general'

import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'
import { marketingAnalyticsSettingsLogic } from '../../logic/marketingAnalyticsSettingsLogic'
import { ConversionGoalDropdown } from '../common/ConversionGoalDropdown'
import { defaultConversionGoalFilter } from '../settings/constants'

export function ConversionGoalModal(): JSX.Element {
    const { conversionGoalModalVisible, draftConversionGoal, conversionGoalInput, uniqueConversionGoalName } =
        useValues(marketingAnalyticsLogic)
    const {
        hideConversionGoalModal,
        setDraftConversionGoal,
        setConversionGoalInput,
        resetConversionGoalInput,
        saveDraftConversionGoal,
    } = useActions(marketingAnalyticsLogic)
    const { conversion_goals } = useValues(marketingAnalyticsSettingsLogic)
    const { addOrUpdateConversionGoal } = useActions(marketingAnalyticsSettingsLogic)

    const [configuredGoalsExpanded, setConfiguredGoalsExpanded] = useState(false)

    const handleConversionGoalChange = useCallback(
        (filter: ConversionGoalFilter): void => {
            setConversionGoalInput({
                ...filter,
                conversion_goal_name:
                    conversionGoalInput?.conversion_goal_name || filter.custom_name || filter.name || 'No name',
            })
        },
        [conversionGoalInput?.conversion_goal_name, setConversionGoalInput]
    )

    const handleApplyConversionGoal = useCallback((): void => {
        if (conversionGoalInput) {
            setDraftConversionGoal({ ...conversionGoalInput, conversion_goal_name: uniqueConversionGoalName })
            setConversionGoalInput({
                ...conversionGoalInput,
                conversion_goal_name: uniqueConversionGoalName,
            })
        }
        hideConversionGoalModal()
    }, [
        conversionGoalInput,
        setDraftConversionGoal,
        setConversionGoalInput,
        uniqueConversionGoalName,
        hideConversionGoalModal,
    ])

    const handleSaveConversionGoal = useCallback((): void => {
        addOrUpdateConversionGoal({ ...conversionGoalInput, conversion_goal_name: uniqueConversionGoalName })
        saveDraftConversionGoal()
        hideConversionGoalModal()
    }, [
        conversionGoalInput,
        addOrUpdateConversionGoal,
        saveDraftConversionGoal,
        uniqueConversionGoalName,
        hideConversionGoalModal,
    ])

    const handleClearConversionGoal = useCallback((): void => {
        resetConversionGoalInput()
        hideConversionGoalModal()
    }, [resetConversionGoalInput, hideConversionGoalModal])

    const handleLoadConfiguredGoal = useCallback(
        (goal: ConversionGoalFilter): void => {
            setConversionGoalInput(goal)
        },
        [setConversionGoalInput]
    )

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
                        onClick={handleClearConversionGoal}
                        disabledReason={!hasAppliedGoal ? 'No active goal to clear' : undefined}
                    >
                        Clear
                    </LemonButton>
                    <div className="flex items-center gap-2">
                        <LemonButton
                            type="secondary"
                            onClick={handleSaveConversionGoal}
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
                            onClick={handleApplyConversionGoal}
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
                    Define conversion goals by selecting events or data warehouse tables. These goals can be used to
                    track and analyze user conversions in your marketing analytics.{' '}
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
                        placeholder="Conversion goal name, e.g. purchase, sign up, download"
                    />
                </div>

                <div>
                    <label className="text-sm font-medium mb-1 block">Event or table</label>
                    <ConversionGoalDropdown
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
                            Configured conversion goals ({conversion_goals.length})
                        </LemonButton>
                        {configuredGoalsExpanded && (
                            <div className="border-t">
                                {conversion_goals.map((goal) => (
                                    <div
                                        key={goal.conversion_goal_id}
                                        className="flex items-center justify-between px-3 py-2 hover:bg-bg-light cursor-pointer border-b last:border-b-0"
                                        onClick={() => handleLoadConfiguredGoal(goal)}
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
