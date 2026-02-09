import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconChevronDown, IconRefresh } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonCheckbox, LemonDropdown, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TZLabel } from 'lib/components/TZLabel'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import {
    AssigneeDisplay,
    AssigneeIconDisplay,
    AssigneeLabelDisplay,
    AssigneeResolver,
    AssigneeSelect,
} from '../../components/Assignee'
import { ChannelsTag } from '../../components/Channels/ChannelsTag'
import { ScenesTabs } from '../../components/ScenesTabs'
import { type Ticket, priorityMultiselectOptions, statusMultiselectOptions } from '../../types'
import { supportTicketsSceneLogic } from './supportTicketsSceneLogic'

export const scene: SceneExport = {
    component: SupportTicketsScene,
    logic: supportTicketsSceneLogic,
    productKey: ProductKey.CONVERSATIONS,
}

export function SupportTicketsScene(): JSX.Element {
    const logic = supportTicketsSceneLogic()
    const { filteredTickets, statusFilter, priorityFilter, assigneeFilter, dateFrom, dateTo, ticketsLoading } =
        useValues(logic)
    const { setStatusFilter, setPriorityFilter, setAssigneeFilter, setDateRange, loadTickets } = useActions(logic)
    const { push } = useActions(router)

    return (
        <SceneContent>
            <SceneTitleSection
                name="Support"
                description=""
                resourceType={{
                    type: 'conversation',
                }}
            />
            <ScenesTabs />
            <div className="flex flex-wrap gap-3 items-center justify-between">
                <div className="flex flex-wrap gap-3 items-center">
                    <DateFilter
                        dateFrom={dateFrom}
                        dateTo={dateTo}
                        onChange={(dateFrom, dateTo) => setDateRange(dateFrom, dateTo)}
                    />
                    <LemonDropdown
                        closeOnClickInside={false}
                        overlay={
                            <div className="space-y-px p-1">
                                {statusMultiselectOptions.map((option) => (
                                    <LemonButton
                                        key={option.key}
                                        type="tertiary"
                                        size="small"
                                        fullWidth
                                        icon={
                                            <LemonCheckbox
                                                checked={statusFilter.includes(option.key)}
                                                className="pointer-events-none"
                                            />
                                        }
                                        onClick={() => {
                                            const newFilter = statusFilter.includes(option.key)
                                                ? statusFilter.filter((s) => s !== option.key)
                                                : [...statusFilter, option.key]
                                            setStatusFilter(newFilter)
                                        }}
                                    >
                                        {option.label}
                                    </LemonButton>
                                ))}
                            </div>
                        }
                    >
                        <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
                            {statusFilter.length === 0
                                ? 'All statuses'
                                : statusFilter.length === 1
                                  ? statusMultiselectOptions.find((o) => o.key === statusFilter[0])?.label
                                  : `${statusFilter.length} statuses`}
                        </LemonButton>
                    </LemonDropdown>
                    <LemonDropdown
                        closeOnClickInside={false}
                        overlay={
                            <div className="space-y-px p-1">
                                {priorityMultiselectOptions.map((option) => (
                                    <LemonButton
                                        key={option.key}
                                        type="tertiary"
                                        size="small"
                                        fullWidth
                                        icon={
                                            <LemonCheckbox
                                                checked={priorityFilter.includes(option.key)}
                                                className="pointer-events-none"
                                            />
                                        }
                                        onClick={() => {
                                            const newFilter = priorityFilter.includes(option.key)
                                                ? priorityFilter.filter((p) => p !== option.key)
                                                : [...priorityFilter, option.key]
                                            setPriorityFilter(newFilter)
                                        }}
                                    >
                                        {option.label}
                                    </LemonButton>
                                ))}
                            </div>
                        }
                    >
                        <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
                            {priorityFilter.length === 0
                                ? 'All priorities'
                                : priorityFilter.length === 1
                                  ? priorityMultiselectOptions.find((o) => o.key === priorityFilter[0])?.label
                                  : `${priorityFilter.length} priorities`}
                        </LemonButton>
                    </LemonDropdown>
                    <AssigneeSelect
                        assignee={assigneeFilter === 'all' || assigneeFilter === 'unassigned' ? null : assigneeFilter}
                        onChange={(assignee) => setAssigneeFilter(assignee ?? 'all')}
                    >
                        {(resolvedAssignee, isOpen) => (
                            <LemonButton size="small" type="secondary" active={isOpen} sideIcon={<IconChevronDown />}>
                                <span className="flex items-center gap-1">
                                    <AssigneeIconDisplay assignee={resolvedAssignee} size="small" />
                                    <AssigneeLabelDisplay
                                        assignee={resolvedAssignee}
                                        size="small"
                                        placeholder="All assignees"
                                    />
                                </span>
                            </LemonButton>
                        )}
                    </AssigneeSelect>
                    <LemonCheckbox
                        checked={assigneeFilter === 'unassigned'}
                        onChange={(checked) => setAssigneeFilter(checked ? 'unassigned' : 'all')}
                        label="Unassigned only"
                    />
                </div>
                <LemonButton
                    type="secondary"
                    icon={<IconRefresh />}
                    loading={ticketsLoading}
                    disabledReason={ticketsLoading ? 'Loading tickets...' : undefined}
                    onClick={loadTickets}
                    size="small"
                    data-attr="refresh-tickets"
                >
                    Refresh
                </LemonButton>
            </div>

            <LemonTable<Ticket>
                dataSource={filteredTickets}
                rowKey="id"
                loading={ticketsLoading}
                onRow={(ticket) => ({
                    onClick: () => push(urls.supportTicketDetail(ticket.id)),
                })}
                rowClassName={(ticket) =>
                    clsx({
                        'bg-primary-alt-highlight': ticket.unread_team_count > 0,
                    })
                }
                columns={[
                    {
                        title: 'Ticket',
                        key: 'key',
                        width: 80,
                        render: (_, ticket) => (
                            <span className="text-xs font-mono text-muted-alt">{ticket.ticket_number}</span>
                        ),
                    },
                    {
                        title: 'Person',
                        key: 'customer',
                        render: (_, ticket) => (
                            <div className="flex items-center gap-2">
                                <PersonDisplay
                                    person={
                                        ticket.person
                                            ? {
                                                  id: ticket.person.id,
                                                  distinct_id: ticket.distinct_id,
                                                  distinct_ids: ticket.person.distinct_ids,
                                                  // Merge anonymous_traits as fallback for missing person properties
                                                  properties: {
                                                      ...ticket.anonymous_traits,
                                                      ...ticket.person.properties,
                                                  },
                                              }
                                            : {
                                                  distinct_id: ticket.distinct_id,
                                                  properties: ticket.anonymous_traits || {},
                                              }
                                    }
                                    withIcon
                                />
                            </div>
                        ),
                    },
                    {
                        title: 'Last message',
                        key: 'last_message',
                        render: (_, ticket) => (
                            <div className="flex items-center gap-2">
                                {ticket.last_message_text ? (
                                    <span
                                        className={clsx('text-xs truncate max-w-md', {
                                            'text-muted-alt': ticket.unread_team_count === 0,
                                            'font-medium': ticket.unread_team_count > 0,
                                        })}
                                    >
                                        {ticket.last_message_text}
                                    </span>
                                ) : (
                                    <span className="text-muted-alt text-xs">—</span>
                                )}
                                {ticket.unread_team_count > 0 && (
                                    <LemonBadge.Number count={ticket.unread_team_count} size="small" status="primary" />
                                )}
                            </div>
                        ),
                    },
                    {
                        title: 'Status',
                        key: 'status',
                        render: (_, ticket) => (
                            <LemonTag
                                type={
                                    ticket.status === 'resolved'
                                        ? 'success'
                                        : ticket.status === 'new'
                                          ? 'primary'
                                          : 'default'
                                }
                            >
                                {ticket.status === 'on_hold' ? 'On hold' : ticket.status}
                            </LemonTag>
                        ),
                    },
                    {
                        title: 'Priority',
                        key: 'priority',
                        render: (_, ticket) =>
                            ticket.priority ? (
                                <LemonTag
                                    type={
                                        ticket.priority === 'high'
                                            ? 'danger'
                                            : ticket.priority === 'medium'
                                              ? 'warning'
                                              : 'default'
                                    }
                                >
                                    {ticket.priority}
                                </LemonTag>
                            ) : (
                                <span className="text-muted-alt text-xs">—</span>
                            ),
                    },
                    {
                        title: 'Assignee',
                        key: 'assignee',
                        render: (_, ticket) => (
                            <AssigneeResolver assignee={ticket.assignee ?? null}>
                                {({ assignee }) => <AssigneeDisplay assignee={assignee} size="small" />}
                            </AssigneeResolver>
                        ),
                    },
                    {
                        title: 'Channel',
                        key: 'channel',
                        render: (_, ticket) => <ChannelsTag channel={ticket.channel_source} />,
                    },
                    {
                        title: 'Created',
                        key: 'created_at',
                        render: (_, ticket) => {
                            return (
                                <span className="text-xs text-muted-alt">
                                    {ticket.created_at && typeof ticket.created_at === 'string' && (
                                        <TZLabel time={ticket.created_at} />
                                    )}
                                </span>
                            )
                        },
                    },
                    {
                        title: 'Updated',
                        key: 'updated_at',
                        align: 'right',
                        render: (_, ticket) => {
                            return (
                                <span className="text-xs text-muted-alt">
                                    {ticket.updated_at && typeof ticket.updated_at === 'string' && (
                                        <TZLabel time={ticket.updated_at} />
                                    )}
                                </span>
                            )
                        },
                    },
                ]}
            />
        </SceneContent>
    )
}
