import { BindLogic, useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'

import { Query } from '~/queries/Query/Query'
import type { DataTableNode } from '~/queries/schema/schema-general'

import { ZendeskTicketsFilters } from 'products/customer_analytics/frontend/components/ZendeskTicketsFilters/ZendeskTicketsFilters'
import { zendeskTicketsFiltersLogic } from 'products/customer_analytics/frontend/components/ZendeskTicketsFilters/zendeskTicketsFiltersLogic'
import {
    useZendeskTicketsQueryContext,
    zendeskGroupTicketsQuery,
    zendeskPersonTicketsQuery,
} from 'products/customer_analytics/frontend/queries/ZendeskTicketsQuery'

import { NotebookNodeAttributeProperties, NotebookNodeProps, NotebookNodeType } from '../types'
import { getCustomerProfileRemoveMenuItem } from './customerProfileNotebookNodeMenu'
import { createPostHogWidgetNode } from './NodeWrapper'
import { notebookNodeLogic } from './notebookNodeLogic'

const Component = ({ attributes }: NotebookNodeProps<NotebookNodeZendeskTicketsAttributes>): JSX.Element | null => {
    const { personId, groupKey, nodeId } = attributes
    const { expanded, notebookLogic } = useValues(notebookNodeLogic)
    const { setMenuItems } = useActions(notebookNodeLogic)
    const mountedZendeskLogic = zendeskTicketsFiltersLogic({ logicKey: nodeId })
    useAttachedLogic(mountedZendeskLogic, notebookLogic)
    const { status, priority, orderBy, orderDirection } = useValues(mountedZendeskLogic)

    useOnMountEffect(() => {
        const removeMenuItem = getCustomerProfileRemoveMenuItem(NotebookNodeType.ZendeskTickets)
        if (removeMenuItem) {
            setMenuItems([removeMenuItem])
        }
    })

    const query = getZendeskTicketsQuery({ personId, groupKey, status, priority, orderBy, orderDirection })
    const context = useZendeskTicketsQueryContext()

    if (!expanded) {
        return null
    }

    if (!query) {
        return <ZendeskTicketsMissingTarget />
    }

    return <Query query={{ ...query, embedded: true }} context={context} attachTo={notebookLogic} />
}

function ZendeskTicketsMissingTarget(): JSX.Element {
    return <div className="text-secondary text-center p-4">Select a person or group to show Zendesk tickets.</div>
}

const Settings = ({
    attributes,
    updateAttributes,
}: NotebookNodeAttributeProperties<NotebookNodeZendeskTicketsAttributes>): JSX.Element => {
    const { nodeId, personId, groupKey } = attributes

    return (
        <BindLogic logic={zendeskTicketsFiltersLogic} props={{ logicKey: nodeId }}>
            <div className="m-2 flex flex-col gap-2">
                <label className="flex flex-col gap-1">
                    <span className="text-xs font-semibold text-secondary">Person UUID</span>
                    <LemonInput
                        value={personId ?? ''}
                        onChange={(value) =>
                            updateAttributes({ personId: value, groupKey: value.trim() ? '' : groupKey })
                        }
                        placeholder="Person UUID"
                    />
                </label>
                <label className="flex flex-col gap-1">
                    <span className="text-xs font-semibold text-secondary">Group key</span>
                    <LemonInput
                        value={groupKey ?? ''}
                        onChange={(value) =>
                            updateAttributes({ groupKey: value, personId: value.trim() ? '' : personId })
                        }
                        placeholder="Group key"
                    />
                </label>
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

type ZendeskTicketsQueryFilters = {
    status?: string
    priority?: string
    orderBy?: string
    orderDirection?: string
}

export function getZendeskTicketsQuery({
    personId,
    groupKey,
    status,
    priority,
    orderBy,
    orderDirection,
}: NotebookNodeZendeskTicketsAttributes & ZendeskTicketsQueryFilters): DataTableNode | null {
    if (personId) {
        return zendeskPersonTicketsQuery({ personId, status, priority, orderBy, orderDirection })
    }

    if (groupKey) {
        return zendeskGroupTicketsQuery({ groupKey, status, priority, orderBy, orderDirection })
    }

    return null
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
