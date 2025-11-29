import { useActions, useValues } from 'kea'

import { IconBookmark, IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'

export function ConversionGoalFilterButton(): JSX.Element {
    const { draftConversionGoal } = useValues(marketingAnalyticsLogic)
    const { showConversionGoalModal, saveConversionGoal, clearConversionGoal } = useActions(marketingAnalyticsLogic)

    if (!draftConversionGoal) {
        return (
            <LemonButton type="secondary" size="small" icon={<IconPlus />} onClick={showConversionGoalModal}>
                Explore a conversion goal
            </LemonButton>
        )
    }

    return (
        <div className="flex items-center gap-1 border rounded px-2 py-1 bg-bg-light">
            <span
                onClick={showConversionGoalModal}
                className="cursor-pointer hover:text-primary text-sm font-medium flex items-center gap-1"
            >
                {draftConversionGoal.conversion_goal_name}
                <IconPencil className="w-3 h-3" />
            </span>
            <LemonButton
                icon={<IconBookmark />}
                size="xsmall"
                onClick={saveConversionGoal}
                tooltip="Save conversion goal"
                type="tertiary"
            />
            <LemonButton
                icon={<IconTrash />}
                size="xsmall"
                onClick={clearConversionGoal}
                tooltip="Clear conversion goal"
                type="tertiary"
            />
        </div>
    )
}
