import { BindLogic, useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { groupLogic } from 'scenes/groups/groupLogic'
import { Notebook } from 'scenes/notebooks/Notebook/Notebook'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'

import { groupsModel } from '~/models/groupsModel'
import { AnyPropertyFilter, CustomerProfileScope, Group, PropertyFilterType, PropertyOperator } from '~/types'

import { customerProfileLogic } from '../customerProfileLogic'
import { CustomerProfileMenu } from './CustomerProfileMenu'
import { FeedbackBanner } from './FeedbackBanner'

interface GroupProfileCanvasProps {
    group: Group
    tabId: string
}

export const GroupProfileCanvas = ({ group, tabId }: GroupProfileCanvasProps): JSX.Element => {
    const { aggregationLabel } = useValues(groupsModel)
    const { reportGroupProfileViewed } = useActions(eventUsageLogic)

    const groupKey = group.group_key
    const groupTypeIndex = group.group_type_index
    const mode = 'canvas'
    const shortId = `${mode}-${groupKey}-${tabId}`
    const attrs = useMemo(
        () => ({
            groupKey,
            groupTypeIndex,
        }),
        [groupKey, groupTypeIndex]
    )
    const customerProfileLogicProps = {
        attrs,
        scope: CustomerProfileScope[`GROUP_${groupTypeIndex}`],
        key: `customer-profile-${groupKey}-${tabId}`,
        canvasShortId: shortId,
    }
    const { content } = useValues(customerProfileLogic(customerProfileLogicProps))

    const groupFilter: AnyPropertyFilter[] = [
        {
            type: PropertyFilterType.EventMetadata,
            key: `$group_${groupTypeIndex}`,
            label: aggregationLabel(groupTypeIndex).singular,
            value: groupKey,
            operator: PropertyOperator.Exact,
        },
    ]

    useOnMountEffect(() => {
        reportGroupProfileViewed()
    })

    return (
        <BindLogic logic={notebookLogic} props={{ shortId, mode, canvasFiltersOverride: groupFilter }}>
            <BindLogic logic={groupLogic} props={{ groupKey, groupTypeIndex, tabId }}>
                <BindLogic logic={customerProfileLogic} props={customerProfileLogicProps}>
                    <div className="flex items-start gap-2">
                        <CustomerProfileMenu />
                        <FeedbackBanner
                            feedbackButtonId="group-profile"
                            message="We're improving the groups experience. Send us your feedback!"
                        />
                    </div>
                    <Notebook
                        editable={false}
                        shortId={shortId}
                        mode={mode}
                        canvasFiltersOverride={groupFilter}
                        initialContent={{
                            type: 'doc',
                            content,
                        }}
                    />
                </BindLogic>
            </BindLogic>
        </BindLogic>
    )
}
