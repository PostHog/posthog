import './EventDefinitionsTable.scss'
import { useActions, useValues } from 'kea'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { EventDefinition, EventDefinitionType } from '~/types'
import {
    EVENT_DEFINITIONS_PER_PAGE,
    eventDefinitionsTableLogic,
} from 'scenes/data-management/events/eventDefinitionsTableLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { organizationLogic } from 'scenes/organizationLogic'
import { EventDefinitionHeader } from 'scenes/data-management/events/DefinitionHeader'
import { humanFriendlyNumber } from 'lib/utils'
import { EventDefinitionProperties } from 'scenes/data-management/events/EventDefinitionProperties'
import { DataManagementPageTabs, DataManagementTab } from 'scenes/data-management/DataManagementPageTabs'
import { UsageDisabledWarning } from 'scenes/events/UsageDisabledWarning'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import {
    ThirtyDayQueryCountTitle,
    ThirtyDayVolumeTitle,
} from 'lib/components/DefinitionPopover/DefinitionPopoverContents'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton, LemonInput, LemonSelect, LemonSelectOptions } from '@posthog/lemon-ui'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { urls } from 'scenes/urls'
import { IconPlayCircle } from 'lib/lemon-ui/icons'

const eventTypeOptions: LemonSelectOptions<EventDefinitionType> = [
    { value: EventDefinitionType.Event, label: 'All events', 'data-attr': 'event-type-option-event' },
    {
        value: EventDefinitionType.EventCustom,
        label: 'Custom events',
        'data-attr': 'event-type-option-event-custom',
    },
    {
        value: EventDefinitionType.EventPostHog,
        label: 'PostHog events',
        'data-attr': 'event-type-option-event-posthog',
    },
]

export const scene: SceneExport = {
    component: EventDefinitionsTable,
    logic: eventDefinitionsTableLogic,
    paramsToProps: () => ({ syncWithUrl: true }),
}

export function EventDefinitionsTable(): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { eventDefinitions, eventDefinitionsLoading, filters } = useValues(eventDefinitionsTableLogic)
    const { loadEventDefinitions, setFilters } = useActions(eventDefinitionsTableLogic)
    const { hasDashboardCollaboration, hasIngestionTaxonomy } = useValues(organizationLogic)

    const columns: LemonTableColumns<EventDefinition> = [
        {
            key: 'icon',
            className: 'definition-column-icon',
            render: function Render(_, definition: EventDefinition) {
                return <EventDefinitionHeader definition={definition} hideText />
            },
        },
        {
            title: 'Name',
            key: 'name',
            className: 'definition-column-name',
            render: function Render(_, definition: EventDefinition) {
                return <EventDefinitionHeader definition={definition} hideIcon asLink />
            },
            sorter: true,
        },
        ...(hasDashboardCollaboration
            ? [
                  {
                      title: 'Tags',
                      key: 'tags',
                      render: function Render(_, definition: EventDefinition) {
                          return <ObjectTags tags={definition.tags ?? []} staticOnly />
                      },
                  } as LemonTableColumn<EventDefinition, keyof EventDefinition | undefined>,
              ]
            : []),
        ...(hasIngestionTaxonomy
            ? [
                  {
                      title: <ThirtyDayVolumeTitle tooltipPlacement="bottom" />,
                      key: 'volume_30_day',
                      align: 'right',
                      render: function Render(_, definition: EventDefinition) {
                          return definition.volume_30_day ? (
                              humanFriendlyNumber(definition.volume_30_day)
                          ) : (
                              <span className="text-muted">—</span>
                          )
                      },
                      sorter: true,
                  } as LemonTableColumn<EventDefinition, keyof EventDefinition | undefined>,
                  {
                      title: <ThirtyDayQueryCountTitle tooltipPlacement="bottom" />,
                      key: 'query_usage_30_day',
                      align: 'right',
                      render: function Render(_, definition: EventDefinition) {
                          return definition.query_usage_30_day ? (
                              humanFriendlyNumber(definition.query_usage_30_day)
                          ) : (
                              <span className="text-muted">—</span>
                          )
                      },
                      sorter: true,
                  } as LemonTableColumn<EventDefinition, keyof EventDefinition | undefined>,
              ]
            : []),
        {
            key: 'actions',
            width: 0,
            render: function RenderActions(_, definition: EventDefinition) {
                return (
                    <More
                        data-attr={`event-definitions-table-more-button-${definition.name}`}
                        overlay={
                            <>
                                <LemonButton
                                    status="stealth"
                                    to={urls.sessionRecordings(undefined, {
                                        filters: {
                                            events: [
                                                {
                                                    id: definition.name,
                                                    type: 'events',
                                                    order: 0,
                                                    name: definition.name,
                                                },
                                            ],
                                        },
                                    })}
                                    fullWidth
                                    sideIcon={<IconPlayCircle />}
                                    data-attr="event-definitions-table-view-recordings"
                                >
                                    View recordings
                                </LemonButton>
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <div data-attr="manage-events-table">
            <PageHeader
                title="Data Management"
                caption="Use data management to organize events that come into PostHog. Reduce noise, clarify usage, and help collaborators get the most value from your data."
                tabbedPage
            />
            {preflight && !preflight?.is_event_property_usage_enabled && <UsageDisabledWarning />}
            <DataManagementPageTabs tab={DataManagementTab.EventDefinitions} />
            <div className="flex justify-between items-center gap-2 mb-4">
                <LemonInput
                    type="search"
                    placeholder="Search for events"
                    onChange={(v) => setFilters({ event: v || '' })}
                    value={filters.event}
                />
                <div className="flex items-center gap-2">
                    <span>Type:</span>
                    <LemonSelect
                        value={filters.event_type}
                        options={eventTypeOptions}
                        data-attr="event-type-filter"
                        dropdownMatchSelectWidth={false}
                        onChange={(value) => {
                            setFilters({ event_type: value as EventDefinitionType })
                        }}
                        size="small"
                    />
                </div>
            </div>
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
                onSort={(newSorting) =>
                    setFilters({
                        ordering: newSorting
                            ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}`
                            : undefined,
                    })
                }
                expandable={{
                    expandedRowRender: function RenderPropertiesTable(definition) {
                        return <EventDefinitionProperties definition={definition} />
                    },
                    rowExpandable: () => true,
                    noIndent: true,
                }}
                dataSource={eventDefinitions.results}
                useURLForSorting={false}
                emptyState="No event definitions"
                nouns={['event', 'events']}
            />
        </div>
    )
}
