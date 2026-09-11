import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCursor } from '@posthog/icons'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { actionsModel } from '~/models/actionsModel'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { ProductTab } from './common'
import { conversionGoalOptionsLogic } from './conversionGoalOptionsLogic'

export interface WebConversionGoalProps {
    value?: { actionId: number } | { customEventName: string } | null
    onChange?: (value: { actionId: number } | { customEventName: string } | null) => void
}

export const WebConversionGoal = ({
    value: propsValue,
    onChange: propsOnChange,
}: WebConversionGoalProps = {}): JSX.Element | null => {
    const { isWindowLessThan } = useWindowSize()

    const { conversionGoal: logicConversionGoal, productTab } = useValues(webAnalyticsLogic)
    const { setConversionGoal: logicSetConversionGoal } = useActions(webAnalyticsLogic)
    const { actions } = useValues(actionsModel)
    const { hasNoConversionGoalOptions } = useValues(conversionGoalOptionsLogic)

    const conversionGoal = propsValue !== undefined ? propsValue : logicConversionGoal
    const setConversionGoal = propsOnChange ?? logicSetConversionGoal

    const [group, setGroup] = useState(TaxonomicFilterGroupType.CustomEvents)
    const value =
        conversionGoal && 'actionId' in conversionGoal ? conversionGoal.actionId : conversionGoal?.customEventName

    if (propsValue === undefined && productTab !== ProductTab.ANALYTICS) {
        return null
    }

    // A goal is either an action or a custom event. With neither, the picker opens on an empty list
    // with nothing to search for, so point at the action that makes the picker usable instead.
    if (!conversionGoal && hasNoConversionGoalOptions) {
        return (
            <AccessControlAction
                resourceType={AccessControlResourceType.Action}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconCursor />}
                    to={urls.createAction()}
                    data-attr="web-analytics-conversion-goal-empty"
                    tooltip="You have no actions or custom events yet. Create an action to track conversions."
                >
                    Set up conversions
                </LemonButton>
            </AccessControlAction>
        )
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
            selectingKeyOnly
            icon={<IconCursor />}
            placeholder={
                isWindowLessThan('xl') ? 'Goal' : isWindowLessThan('2xl') ? 'Conversion goal' : 'Add conversion goal'
            }
            placeholderClass=""
            size="small"
        />
    )
}
