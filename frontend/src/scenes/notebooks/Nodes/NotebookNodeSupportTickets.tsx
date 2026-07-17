import { BindLogic, useActions, useValues } from 'kea'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ConversationsDisabledBanner } from 'products/conversations/frontend/components/ConversationsDisabledBanner'
import {
    SupportTicketsTable,
    SupportTicketsTableFilters,
} from 'products/conversations/frontend/scenes/tickets/SupportTicketsScene'
import { supportTicketsSceneLogic } from 'products/conversations/frontend/scenes/tickets/supportTicketsSceneLogic'

import { NotebookNodeAttributeProperties, NotebookNodeProps, NotebookNodeType } from '../types'
import { getCustomerProfileRemoveMenuItem } from './customerProfileNotebookNodeMenu'
import { createPostHogWidgetNode } from './NodeWrapper'
import { notebookNodeLogic } from './notebookNodeLogic'

const Component = ({ attributes }: NotebookNodeProps<NotebookNodeSupportTicketsAttributes>): JSX.Element | null => {
    const { distinctIds, nodeId } = attributes
    const { expanded, notebookLogic } = useValues(notebookNodeLogic)
    const { setMenuItems } = useActions(notebookNodeLogic)
    const logicProps = { key: nodeId, distinctIds }
    const mountedLogic = supportTicketsSceneLogic(logicProps)
    useAttachedLogic(mountedLogic, notebookLogic)
    const { currentTeam } = useValues(teamLogic)

    useOnMountEffect(() => {
        const removeMenuItem = getCustomerProfileRemoveMenuItem(NotebookNodeType.SupportTickets)
        if (removeMenuItem) {
            setMenuItems([removeMenuItem])
        }
    })

    if (!expanded) {
        return null
    }

    // When support is off, never query the disabled product — show the "set up support"
    // prompt instead. (The panel is hidden entirely for teams that use Zendesk but not
    // support; that visibility decision lives in customerProfileLogic's content filter.)
    if (!currentTeam?.conversations_enabled) {
        return <ConversationsDisabledBanner />
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
