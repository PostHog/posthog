import { BindLogic, useValues } from 'kea'

import { ZendeskSourceSetupPrompt } from 'scenes/data-pipelines/ZendeskSourceSetupPrompt'

import { Query } from '~/queries/Query/Query'

import { ZendeskTicketsFilters } from 'products/customer_analytics/frontend/components/ZendeskTicketsFilters/ZendeskTicketsFilters'
import { zendeskTicketsFiltersLogic } from 'products/customer_analytics/frontend/components/ZendeskTicketsFilters/zendeskTicketsFiltersLogic'
import {
    useZendeskTicketsQueryContext,
    zendeskTicketsQuery,
} from 'products/customer_analytics/frontend/queries/ZendeskTicketsQuery'

import { NotebookNodeAttributeProperties, NotebookNodeProps, NotebookNodeType } from '../types'
import { createPostHogWidgetNode } from './NodeWrapper'
import { notebookNodeLogic } from './notebookNodeLogic'

const Component = ({ attributes }: NotebookNodeProps<NotebookNodeZendeskTicketsAttributes>): JSX.Element | null => {
    const { personId } = attributes
    const { expanded } = useValues(notebookNodeLogic)
    const { status, priority, orderBy, orderDirection } = useValues(zendeskTicketsFiltersLogic({ logicKey: personId }))

    const query = zendeskTicketsQuery({ personId, status, priority, orderBy, orderDirection })
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
    const { personId } = attributes

    return (
        <BindLogic logic={zendeskTicketsFiltersLogic} props={{ logicKey: personId }}>
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
    personId: string
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
    },
})
