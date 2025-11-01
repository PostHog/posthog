import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCursor } from '@posthog/icons'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { actionsModel } from '~/models/actionsModel'

import { ProductTab } from './common'

/**
 * WebConversionGoal - Flexible conversion goal selector for Web Analytics
 *
 * Can be used in two modes:
 * 1. Web Analytics Dashboard mode: No props needed, uses webAnalyticsLogic
 * 2. Standalone mode: Pass value and onChange props
 *
 * This allows the component to be reused in Product Analytics insights.
 */

export interface WebConversionGoalProps {
    value?: { actionId: number } | { customEventName: string } | null
    onChange?: (value: { actionId: number } | { customEventName: string } | null) => void
}

export const WebConversionGoal = ({
    value: propsValue,
    onChange: propsOnChange,
}: WebConversionGoalProps = {}): JSX.Element | null => {
    const { isWindowLessThan } = useWindowSize()

    // Always call hooks unconditionally (React Rules of Hooks)
    const { conversionGoal: logicConversionGoal, productTab } = useValues(webAnalyticsLogic)
    const { setConversionGoal: logicSetConversionGoal } = useActions(webAnalyticsLogic)
    const { actions } = useValues(actionsModel)

    // Use props if provided, otherwise use logic values
    const conversionGoal = propsValue !== undefined ? propsValue : logicConversionGoal
    const setConversionGoal = propsOnChange ?? logicSetConversionGoal

    const [group, setGroup] = useState(TaxonomicFilterGroupType.CustomEvents)
    const value =
        conversionGoal && 'actionId' in conversionGoal ? conversionGoal.actionId : conversionGoal?.customEventName

    // Only check productTab if using logic (dashboard mode)
    if (propsValue === undefined && productTab !== ProductTab.ANALYTICS) {
        return null
    }

    return (
        <TaxonomicPopover<number | string>
            allowClear
            data-attr="web-analytics-conversion-filter"
            groupType={group}
            value={value}
            onChange={(changedValue, groupType) => {
                if (groupType === TaxonomicFilterGroupType.Actions && typeof changedValue === 'number') {
                    setConversionGoal({ actionId: changedValue })
                    setGroup(TaxonomicFilterGroupType.Actions)
                } else if (
                    groupType === TaxonomicFilterGroupType.CustomEvents &&
                    typeof changedValue === 'string' &&
                    changedValue
                ) {
                    setConversionGoal({ customEventName: changedValue })
                    setGroup(TaxonomicFilterGroupType.CustomEvents)
                } else {
                    setConversionGoal(null)
                }
            }}
            renderValue={() => {
                if (!conversionGoal) {
                    return null
                } else if ('actionId' in conversionGoal) {
                    const conversionGoalAction = actions.find((a) => a.id === conversionGoal.actionId)
                    return (
                        <span className="text-overflow max-w-full">
                            {conversionGoalAction?.name ?? 'Conversion goal'}
                        </span>
                    )
                }
                return <span className="text-overflow max-w-full">{conversionGoal?.customEventName}</span>
            }}
            groupTypes={[TaxonomicFilterGroupType.CustomEvents, TaxonomicFilterGroupType.Actions]}
            icon={<IconCursor />}
            placeholder={
                isWindowLessThan('xl') ? 'Goal' : isWindowLessThan('2xl') ? 'Conversion goal' : 'Add conversion goal'
            }
            placeholderClass=""
            size="small"
        />
    )
}
