import { BindLogic, BuiltLogic, LogicWrapper, useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { groupLogic } from 'scenes/groups/groupLogic'
import { Notebook } from 'scenes/notebooks/Notebook/Notebook'
import { NotebookLogicProps, notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'

import { groupsModel } from '~/models/groupsModel'
import { AnyPropertyFilter, CustomerProfileScope, Group, PropertyFilterType, PropertyOperator } from '~/types'

import { customerProfileLogic } from '../customerProfileLogic'
import { CustomerProfileMenu } from './CustomerProfileMenu'
import { FeedbackBanner } from './FeedbackBanner'

interface GroupProfileCanvasProps {
    group: Group
    tabId: string
    attachTo: BuiltLogic | LogicWrapper
}

export const GroupProfileCanvas = ({ group, tabId, attachTo }: GroupProfileCanvasProps): JSX.Element => {
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
    const notebookLogicProps: NotebookLogicProps = {
        shortId,
        mode,
        canvasFiltersOverride: groupFilter,
    }
    const mountedNotebookLogic = notebookLogic(notebookLogicProps)
    useAttachedLogic(mountedNotebookLogic, attachTo)

    return (
        <BindLogic logic={notebookLogic} props={notebookLogicProps}>
            <BindLogic logic={groupLogic} props={{ groupKey, groupTypeIndex, tabId }}>
                <BindLogic logic={customerProfileLogic} props={customerProfileLogicProps}>
                    <FeedbackBanner
                        feedbackButtonId="group-profile"
                        message="We're improving the groups experience. Send us your feedback!"
                    />
                    <CustomerProfileMenu />
                    <Notebook
                        editable={false}
                        shortId={shortId}
                        mode={mode}
                        className="NotebookProfileCanvas"
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
