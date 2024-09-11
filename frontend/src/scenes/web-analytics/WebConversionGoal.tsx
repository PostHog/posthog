import { useActions, useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { actionsModel } from '~/models/actionsModel'

export const WebConversionGoal = (): JSX.Element => {
    const { conversionGoal } = useValues(webAnalyticsLogic)
    const { setConversionGoal } = useActions(webAnalyticsLogic)
    const { actions } = useValues(actionsModel)
    return (
        <>
            <TaxonomicPopover<number>
                data-attr="web-analytics-conversion-filter"
                groupType={TaxonomicFilterGroupType.Actions}
                value={conversionGoal?.actionId}
                onChange={(changedValue) => {
                    setConversionGoal({ actionId: changedValue })
                }}
                renderValue={(value) => {
                    const conversionGoalAction = actions.find((a) => a.id === value)
                    return (
                        <span className="text-overflow max-w-full">
                            {conversionGoalAction?.name ?? 'Conversion goal'}
                        </span>
                    )
                }}
                groupTypes={[TaxonomicFilterGroupType.Actions]}
                placeholder="Add conversion goal"
                placeholderClass=""
                allowClear={true}
            />
        </>
    )
}
