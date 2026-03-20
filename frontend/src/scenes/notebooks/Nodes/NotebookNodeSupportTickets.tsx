import { BindLogic, useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'

import {
    SupportTicketsTable,
    SupportTicketsTableFilters,
} from 'products/conversations/frontend/scenes/tickets/SupportTicketsScene'
import { supportTicketsSceneLogic } from 'products/conversations/frontend/scenes/tickets/supportTicketsSceneLogic'
import { customerProfileLogic } from 'products/customer_analytics/frontend/customerProfileLogic'

import { NotebookNodeAttributeProperties, NotebookNodeProps, NotebookNodeType } from '../types'
import { createPostHogWidgetNode } from './NodeWrapper'
import { notebookNodeLogic } from './notebookNodeLogic'

const Component = ({ attributes }: NotebookNodeProps<NotebookNodeSupportTicketsAttributes>): JSX.Element | null => {
    const { distinctIds, nodeId } = attributes
    const { expanded, notebookLogic } = useValues(notebookNodeLogic)
    const { setMenuItems } = useActions(notebookNodeLogic)
    const logicProps = { key: nodeId, distinctIds }
    const mountedLogic = supportTicketsSceneLogic(logicProps)
    useAttachedLogic(mountedLogic, notebookLogic)
    const { removeNode } = useActions(customerProfileLogic)

    useOnMountEffect(() => {
        setMenuItems([
            {
                label: 'Remove',
                onClick: () => removeNode(NotebookNodeType.SupportTickets),
                sideIcon: <IconX />,
                status: 'danger',
            },
        ])
    })

    if (!expanded) {
        return null
    }

    return (
        <BindLogic logic={supportTicketsSceneLogic} props={logicProps}>
            <SupportTicketsTable embedded />
        </BindLogic>
    )
}

const Settings = ({
    attributes,
}: NotebookNodeAttributeProperties<NotebookNodeSupportTicketsAttributes>): JSX.Element => {
    const { nodeId, distinctIds } = attributes
    const logicProps = { key: nodeId, distinctIds }

    return (
        <BindLogic logic={supportTicketsSceneLogic} props={logicProps}>
            <SupportTicketsTableFilters />
        </BindLogic>
    )
}

type NotebookNodeSupportTicketsAttributes = {
    personId?: string
    distinctIds?: string[]
}

export const NotebookNodeSupportTickets = createPostHogWidgetNode<NotebookNodeSupportTicketsAttributes>({
    nodeType: NotebookNodeType.SupportTickets,
    titlePlaceholder: 'Support tickets',
    Component,
    Settings,
    resizeable: false,
    expandable: true,
    startExpanded: true,
    attributes: {
        personId: {},
        distinctIds: {},
    },
})
