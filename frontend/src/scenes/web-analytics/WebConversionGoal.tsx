import { useActions, useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { useState } from 'react'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { actionsModel } from '~/models/actionsModel'

export const WebConversionGoal = (): JSX.Element | null => {
    const { conversionGoal } = useValues(webAnalyticsLogic)
    const { setConversionGoal } = useActions(webAnalyticsLogic)
    const { actions } = useValues(actionsModel)
    const [group, setGroup] = useState(TaxonomicFilterGroupType.CustomEvents)
    const value =
        conversionGoal && 'actionId' in conversionGoal ? conversionGoal.actionId : conversionGoal?.customEventName
    return (
        <TaxonomicPopover<number | string>
            groupType={group}
            data-attr="web-analytics-conversion-filter"
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
            placeholder="Add conversion goal"
            placeholderClass=""
            allowClear={true}
            size="small"
        />
    )
}
