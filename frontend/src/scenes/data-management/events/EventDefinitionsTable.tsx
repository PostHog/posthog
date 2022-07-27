import './EventDefinitionsTable.scss'
import React from 'react'
import { useActions, useValues } from 'kea'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/components/LemonTable'
import { CombinedEvent, CombinedEventType } from '~/types'
import {
    EVENT_DEFINITIONS_PER_PAGE,
    eventDefinitionsTableLogic,
    isActionEvent,
} from 'scenes/data-management/events/eventDefinitionsTableLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { organizationLogic } from 'scenes/organizationLogic'
import { ActionHeader, EventDefinitionHeader } from 'scenes/data-management/events/DefinitionHeader'
import { humanFriendlyNumber } from 'lib/utils'
import { EventDefinitionProperties } from 'scenes/data-management/events/EventDefinitionProperties'
import { Alert, Col, Input, Row } from 'antd'
import { DataManagementPageTabs, DataManagementTab } from 'scenes/data-management/DataManagementPageTabs'
import { UsageDisabledWarning } from 'scenes/events/UsageDisabledWarning'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { ThirtyDayQueryCountTitle, ThirtyDayVolumeTitle } from 'lib/components/DefinitionPopup/DefinitionPopupContents'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import { teamLogic } from 'scenes/teamLogic'
import { ActionEvent, IconWebhook, UnverifiedEvent } from 'lib/components/icons'
import { NewActionButton } from 'scenes/actions/NewActionButton'
import { TZLabel } from 'lib/components/TimezoneAware'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonSelect, LemonSelectOptions } from '@posthog/lemon-ui'

const eventTypeOptions: LemonSelectOptions = {
    [CombinedEventType.All]: {
        label: 'All types',
    },
    [CombinedEventType.ActionEvent]: {
        label: 'Calculated events',
        icon: <ActionEvent />,
    },
    [CombinedEventType.Event]: {
        label: 'Events',
        icon: <UnverifiedEvent />,
    },
}

export const scene: SceneExport = {
    component: EventDefinitionsTable,
    logic: eventDefinitionsTableLogic,
    paramsToProps: () => ({ syncWithUrl: true }),
}

export function EventDefinitionsTable(): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { eventDefinitions, eventDefinitionsLoading, filters, shouldSimplifyActions } =
        useValues(eventDefinitionsTableLogic)
    const { currentTeam } = useValues(teamLogic)
    const { loadEventDefinitions, setFilters } = useActions(eventDefinitionsTableLogic)
    const { hasDashboardCollaboration, hasIngestionTaxonomy } = useValues(organizationLogic)

    const columns: LemonTableColumns<CombinedEvent> = [
        {
            key: 'icon',
            className: 'definition-column-icon',
            render: function Render(_, definition: CombinedEvent) {
                if (isActionEvent(definition)) {
                    return <ActionHeader definition={definition} hideText />
                }
                return <EventDefinitionHeader definition={definition} hideText />
            },
        },
        {
            title: 'Name',
            key: 'name',
            className: 'definition-column-name',
            render: function Render(_, definition: CombinedEvent) {
                if (isActionEvent(definition)) {
                    return <ActionHeader definition={definition} hideIcon asLink />
                }
                return <EventDefinitionHeader definition={definition} hideIcon asLink shouldSimplifyActions />
            },
            sorter: (a, b) => a.name?.localeCompare(b.name ?? '') ?? 0,
        },
        ...(hasDashboardCollaboration
            ? [
                  {
                      title: 'Tags',
                      key: 'tags',
                      render: function Render(_, definition: CombinedEvent) {
                          return <ObjectTags tags={definition.tags ?? []} staticOnly />
                      },
                  } as LemonTableColumn<CombinedEvent, keyof CombinedEvent | undefined>,
              ]
            : []),
        ...(shouldSimplifyActions
            ? [
                  {
                      title: 'Created by',
                      key: 'created_by',
                      align: 'left',
                      render: function Render(_, definition: CombinedEvent) {
                          const created_by = isActionEvent(definition) ? definition.created_by : definition.owner
                          return (
                              <Row align="middle" wrap={false}>
                                  {created_by && (
                                      <ProfilePicture name={created_by.first_name} email={created_by.email} size="md" />
                                  )}
                                  <div
                                      style={{
                                          maxWidth: 250,
                                          width: 'auto',
                                          verticalAlign: 'middle',
                                          marginLeft: created_by ? 8 : 0,
                                          color: created_by ? undefined : 'var(--muted)',
                                      }}
                                  >
                                      {created_by ? created_by.first_name || created_by.email : '—'}
                                  </div>
                              </Row>
                          )
                      },
                  } as LemonTableColumn<CombinedEvent, keyof CombinedEvent | undefined>,
                  {
                      title: 'Last updated',
                      key: 'last_updated',
                      align: 'left',
                      render: function Render(_, definition: CombinedEvent) {
                          const last_updated_at = definition.last_updated_at
                          return last_updated_at ? (
                              <div style={{ whiteSpace: 'nowrap' }}>
                                  <TZLabel time={last_updated_at} />
                              </div>
                          ) : (
                              <span style={{ color: 'var(--muted)' }}>—</span>
                          )
                      },
                      sorter: (a, b) => (new Date(a.last_updated_at || 0) > new Date(b.last_updated_at || 0) ? 1 : -1),
                  } as LemonTableColumn<CombinedEvent, keyof CombinedEvent | undefined>,
                  {
                      title: 'Webhook',
                      key: 'webhook',
                      align: 'center',
                      render: function Render(_, definition: CombinedEvent) {
                          if (
                              isActionEvent(definition) &&
                              !!currentTeam?.slack_incoming_webhook &&
                              !!definition.post_to_slack
                          ) {
                              return <IconWebhook />
                          }
                          return <></>
                      },
                  } as LemonTableColumn<CombinedEvent, keyof CombinedEvent | undefined>,
              ]
            : []),
        ...(!shouldSimplifyActions && hasIngestionTaxonomy
            ? [
                  {
                      title: <ThirtyDayVolumeTitle tooltipPlacement="bottom" />,
                      key: 'volume_30_day',
                      align: 'right',
                      render: function Render(_, definition: CombinedEvent) {
                          if (isActionEvent(definition)) {
                              return <span className="text-muted">—</span>
                          }
                          return definition.volume_30_day ? (
                              humanFriendlyNumber(definition.volume_30_day)
                          ) : (
                              <span className="text-muted">—</span>
                          )
                      },
                      sorter: (a, b) =>
                          !isActionEvent(a) && !isActionEvent(b)
                              ? (a?.volume_30_day ?? 0) - (b?.volume_30_day ?? 0)
                              : 0,
                  } as LemonTableColumn<CombinedEvent, keyof CombinedEvent | undefined>,
                  {
                      title: <ThirtyDayQueryCountTitle tooltipPlacement="bottom" />,
                      key: 'query_usage_30_day',
                      align: 'right',
                      render: function Render(_, definition: CombinedEvent) {
                          if (isActionEvent(definition)) {
                              return <span className="text-muted">—</span>
                          }
                          return definition.query_usage_30_day ? (
                              humanFriendlyNumber(definition.query_usage_30_day)
                          ) : (
                              <span className="text-muted">—</span>
                          )
                      },
                      sorter: (a, b) =>
                          !isActionEvent(a) && !isActionEvent(b)
                              ? (a?.query_usage_30_day ?? 0) - (b?.query_usage_30_day ?? 0)
                              : 0,
                  } as LemonTableColumn<CombinedEvent, keyof CombinedEvent | undefined>,
              ]
            : []),
    ]

    return (
        <div data-attr="manage-events-table">
            <PageHeader
                title="Data Management"
                caption="Use data management to organize events that come into PostHog. Reduce noise, clarify usage, and help collaborators get the most value from your data."
                tabbedPage
                buttons={shouldSimplifyActions && <NewActionButton />}
            />
            {shouldSimplifyActions && (
                <Alert
                    style={{ marginBottom: 16, display: 'flex', alignItems: 'center' }}
                    message="Actions have moved to the Events tab"
                    description={
                        <>
                            Actions are now called calculated events and can be found in the events tab. You can create
                            a new calculated event (formerly known as an Action) by clicking the "New calculated event"
                            button.
                        </>
                    }
                    type="info"
                    showIcon
                    closable
                />
            )}
            <DataManagementPageTabs tab={DataManagementTab.EventDefinitions} />
            {preflight && !preflight?.is_event_property_usage_enabled && (
                <UsageDisabledWarning tab="Event Definitions" />
            )}
            <Row
                justify="space-between"
                style={{
                    paddingBottom: '1rem',
                    marginBottom: '1rem',
                    borderBottom: '1px solid var(--border)',
                    gap: '0.75rem',
                }}
            >
                <Col>
                    <Input.Search
                        placeholder="Search for events"
                        allowClear
                        enterButton
                        value={filters.event}
                        style={{ maxWidth: 600, width: 'initial' }}
                        onChange={(e) => {
                            setFilters({ event: e.target.value || '' })
                        }}
                    />
                </Col>
                {shouldSimplifyActions && (
                    <Row style={{ gap: '0.75rem' }}>
                        <Col style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
                            Type:
                            <LemonSelect
                                value={filters.event_type}
                                options={eventTypeOptions}
                                data-attr="event-type-filter"
                                dropdownMatchSelectWidth={false}
                                bordered
                                onChange={(value) => {
                                    setFilters({ event_type: value as CombinedEventType })
                                }}
                                size="small"
                            />
                        </Col>
                    </Row>
                )}
            </Row>
            <LemonTable
                columns={columns}
                className="events-definition-table"
                data-attr="events-definition-table"
                loading={eventDefinitionsLoading}
                rowKey="id"
                pagination={{
                    controlled: true,
                    currentPage: eventDefinitions?.page ?? 1,
                    entryCount: eventDefinitions?.count ?? 0,
                    pageSize: EVENT_DEFINITIONS_PER_PAGE,
                    onForward: !!eventDefinitions.next
                        ? () => {
                              loadEventDefinitions(eventDefinitions.next)
                          }
                        : undefined,
                    onBackward: !!eventDefinitions.previous
                        ? () => {
                              loadEventDefinitions(eventDefinitions.previous)
                          }
                        : undefined,
                }}
                expandable={{
                    expandedRowRender: function RenderPropertiesTable(definition) {
                        if (isActionEvent(definition)) {
                            return null
                        }
                        return <EventDefinitionProperties definition={definition} />
                    },
                    rowExpandable: (definition) => {
                        return !isActionEvent(definition)
                    },
                    noIndent: true,
                }}
                dataSource={eventDefinitions.results}
                emptyState="No event definitions"
                nouns={['event', 'events']}
            />
        </div>
    )
}
