import { useActions, useValues } from 'kea'

import { IconBookmark, IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { Button, ButtonGroup } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { marketingAnalyticsLogic } from '../../logic/marketingAnalyticsLogic'

export function ConversionGoalFilterButton(): JSX.Element {
    const { draftConversionGoal } = useValues(marketingAnalyticsLogic)
    const { showConversionGoalModal, saveConversionGoal, clearConversionGoal } = useActions(marketingAnalyticsLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        if (!draftConversionGoal) {
            return (
                <Button
                    variant="outline"
                    onClick={showConversionGoalModal}
                    tooltip="Preview a conversion goal on this dashboard. Save it if you want to keep it."
                    data-attr="marketing-analytics-add-conversion-goal"
                >
                    <IconPlus />
                    Add conversion goal
                </Button>
            )
        }

        return (
            <ButtonGroup className="max-w-full min-w-0">
                <Button variant="outline" onClick={showConversionGoalModal} className="min-w-0 shrink">
                    <span className="truncate">{draftConversionGoal.conversion_goal_name}</span>
                    <IconPencil />
                </Button>
                <Button
                    variant="outline"
                    size="icon"
                    onClick={saveConversionGoal}
                    aria-label="Save conversion goal"
                    tooltip="Save conversion goal"
                >
                    <IconBookmark />
                </Button>
                <Button
                    variant="outline"
                    size="icon"
                    onClick={clearConversionGoal}
                    aria-label="Clear conversion goal"
                    tooltip="Clear conversion goal"
                >
                    <IconTrash />
                </Button>
            </ButtonGroup>
        )
    }

    if (!draftConversionGoal) {
        return (
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconPlus />}
                onClick={showConversionGoalModal}
                tooltip="Preview a conversion goal on this dashboard. Save it if you want to keep it."
                data-attr="marketing-analytics-add-conversion-goal"
            >
                Add conversion goal
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
