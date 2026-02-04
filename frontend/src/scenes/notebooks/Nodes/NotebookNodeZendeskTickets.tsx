import { BindLogic, useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { ZendeskSourceSetupPrompt } from 'scenes/data-pipelines/ZendeskSourceSetupPrompt'

import { Query } from '~/queries/Query/Query'

import { ZendeskTicketsFilters } from 'products/customer_analytics/frontend/components/ZendeskTicketsFilters/ZendeskTicketsFilters'
import { zendeskTicketsFiltersLogic } from 'products/customer_analytics/frontend/components/ZendeskTicketsFilters/zendeskTicketsFiltersLogic'
import { customerProfileLogic } from 'products/customer_analytics/frontend/customerProfileLogic'
import {
    useZendeskTicketsQueryContext,
    zendeskGroupTicketsQuery,
    zendeskPersonTicketsQuery,
} from 'products/customer_analytics/frontend/queries/ZendeskTicketsQuery'

import { NotebookNodeAttributeProperties, NotebookNodeProps, NotebookNodeType } from '../types'
import { createPostHogWidgetNode } from './NodeWrapper'
import { notebookNodeLogic } from './notebookNodeLogic'

const Component = ({ attributes }: NotebookNodeProps<NotebookNodeZendeskTicketsAttributes>): JSX.Element | null => {
    const { personId, groupKey, nodeId } = attributes
    const { expanded } = useValues(notebookNodeLogic)
    const { setMenuItems } = useActions(notebookNodeLogic)
    const { status, priority, orderBy, orderDirection } = useValues(zendeskTicketsFiltersLogic({ logicKey: nodeId }))
    const { removeNode } = useActions(customerProfileLogic)

    useOnMountEffect(() => {
        setMenuItems([
            {
                label: 'Remove',
                onClick: () => removeNode(NotebookNodeType.ZendeskTickets),
                sideIcon: <IconX />,
                status: 'danger',
            },
        ])
    })

    const query = personId
        ? zendeskPersonTicketsQuery({ personId, status, priority, orderBy, orderDirection })
        : groupKey
          ? zendeskGroupTicketsQuery({ groupKey, status, priority, orderBy, orderDirection })
          : null

    if (!query) {
        throw new Error('Missing query')
    }

    const context = useZendeskTicketsQueryContext()

    if (!expanded) {
        return null
    }

    return (
        <ZendeskSourceSetupPrompt className="border-none">
            <Query query={{ ...query, embedded: true }} context={context} />
        </ZendeskSourceSetupPrompt>
    )
}

const Settings = ({
    attributes,
}: NotebookNodeAttributeProperties<NotebookNodeZendeskTicketsAttributes>): JSX.Element => {
    const { nodeId } = attributes

    return (
        <BindLogic logic={zendeskTicketsFiltersLogic} props={{ logicKey: nodeId }}>
            <div className="m-2">
                <ZendeskTicketsFilters.Root>
                    <ZendeskTicketsFilters.Status />
                    <ZendeskTicketsFilters.Priority />
                    <ZendeskTicketsFilters.OrderBy />
                </ZendeskTicketsFilters.Root>
            </div>
        </BindLogic>
    )
}

type NotebookNodeZendeskTicketsAttributes = {
    personId?: string
    groupKey?: string
}

export const NotebookNodeZendeskTickets = createPostHogWidgetNode<NotebookNodeZendeskTicketsAttributes>({
    nodeType: NotebookNodeType.ZendeskTickets,
    titlePlaceholder: 'Zendesk tickets',
    Component,
    Settings,
    resizeable: false,
    expandable: true,
    startExpanded: true,
    attributes: {
        personId: {},
        groupKey: {},
    },
})
