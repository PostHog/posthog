import { Combobox } from '@base-ui/react/combobox'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo, useState } from 'react'

import { IconChevronRight, IconDatabase, IconPeople } from '@posthog/icons'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { urls } from 'scenes/urls'

import { FEATURE_FLAGS } from '~/lib/constants'

import { iconForType } from '../ProjectTree/defaultTree'

interface DataItem {
    id: string
    label: string
    icon: React.ReactNode
    href: string
    flag?: string
}

interface DataGroup {
    value: string
    items: DataItem[]
}

function useDataMenuGroups(): DataGroup[] {
    const { featureFlags } = useValues(featureFlagLogic)

    const groups: DataGroup[] = useMemo(
        () =>
            [
                {
                    value: 'People',
                    items: [
                        { id: 'persons', label: 'Persons', icon: iconForType('persons'), href: urls.persons() },
                        {
                            id: 'cohorts',
                            label: 'Cohorts',
                            icon: <IconPeople className="size-4 text-secondary" />,
                            href: urls.cohorts(),
                        },
                    ],
                },
                {
                    value: 'Groups',
                    items: [{ id: 'groups', label: 'Groups', icon: iconForType('group'), href: urls.groups(0) }],
                },
                {
                    value: 'Metadata',
                    items: [
                        {
                            id: 'annotations',
                            label: 'Annotations',
                            icon: iconForType('annotation'),
                            href: urls.annotations(),
                        },
                        { id: 'comments', label: 'Comments', icon: iconForType('comment'), href: urls.comments() },
                    ],
                },
                {
                    value: 'Behavior',
                    items: [
                        {
                            id: 'support',
                            label: 'Support',
                            icon: iconForType('conversations'),
                            href: urls.supportTickets(),
                            flag: FEATURE_FLAGS.PRODUCT_SUPPORT,
                        },
                    ],
                },
                {
                    value: 'Tools',
                    items: [
                        {
                            id: 'endpoints',
                            label: 'Endpoints',
                            icon: iconForType('endpoints'),
                            href: urls.endpoints(),
                            flag: FEATURE_FLAGS.ENDPOINTS,
                        },
                        { id: 'models', label: 'Models', icon: iconForType('sql_editor'), href: urls.models() },
                    ],
                },
                {
                    value: 'Schema',
                    items: [
                        { id: 'actions', label: 'Actions', icon: iconForType('action'), href: urls.actions() },
                        {
                            id: 'event-definitions',
                            label: 'Event definitions',
                            icon: iconForType('event_definition'),
                            href: urls.eventDefinitions(),
                        },
                        {
                            id: 'property-definitions',
                            label: 'Property definitions',
                            icon: iconForType('property_definition'),
                            href: urls.propertyDefinitions(),
                        },
                        {
                            id: 'property-groups',
                            label: 'Property groups',
                            icon: iconForType('event_definition'),
                            href: urls.schemaManagement(),
                            flag: FEATURE_FLAGS.SCHEMA_MANAGEMENT,
                        },
                        {
                            id: 'revenue-definitions',
                            label: 'Revenue definitions',
                            icon: iconForType('revenue_analytics_metadata'),
                            href: urls.revenueSettings(),
                        },
                        {
                            id: 'sql-variables',
                            label: 'SQL variables',
                            href: urls.variables(),
                            icon: <IconDatabase className="size-4 text-secondary" />,
                        },
                    ],
                },
                {
                    value: 'Pipeline',
                    items: [
                        {
                            id: 'destinations',
                            label: 'Destinations',
                            icon: iconForType('data_pipeline_metadata'),
                            href: urls.destinations(),
                        },
                        {
                            id: 'ingestion-warnings',
                            label: 'Event ingestion warnings',
                            icon: iconForType('ingestion_warning'),
                            href: urls.ingestionWarnings(),
                        },
                        {
                            id: 'sources',
                            label: 'Sources',
                            icon: iconForType('data_pipeline_metadata'),
                            href: urls.sources(),
                        },
                        {
                            id: 'transformations',
                            label: 'Transformations',
                            icon: iconForType('data_pipeline_metadata'),
                            href: urls.transformations(),
                        },
                    ],
                },
            ]
                .map((group) => ({
                    ...group,
                    items: group.items.filter(
                        (item) => !item.flag || (featureFlags as Record<string, boolean>)[item.flag]
                    ),
                }))
                .filter((group) => group.items.length > 0),
        [featureFlags]
    )

    return groups
}

const menuItemStyles =
    'flex items-center gap-2 px-2 py-1.5 rounded-sm text-sm cursor-pointer hover:bg-fill-button-tertiary-hover outline-none data-[highlighted]:bg-fill-button-tertiary-hover'

export function DataMenu(): JSX.Element {
    const groups = useDataMenuGroups()
    const [open, setOpen] = useState(false)

    return (
        <Combobox.Root
            open={open}
            onOpenChange={setOpen}
            items={groups}
            itemToStringValue={(item: DataItem) => item.label}
            defaultInputValue=""
            autoHighlight
        >
            <Combobox.Trigger
                render={
                    <ButtonPrimitive menuItem>
                        <IconDatabase className="size-4 text-secondary" />
                        <span className="flex-1 text-left">Data</span>
                        <IconChevronRight className="size-3 text-secondary" />
                    </ButtonPrimitive>
                }
            />
            <Combobox.Portal>
                <Combobox.Positioner
                    className="z-[var(--z-popover)]"
                    side="right"
                    align="start"
                    sideOffset={6}
                    alignOffset={-4}
                >
                    <Combobox.Popup className="primitive-menu-content min-w-[250px] flex flex-col p-1 max-h-(--available-height)">
                        <Combobox.Input
                            placeholder="Search data"
                            className="w-full px-2 py-1.5 text-sm rounded-sm border border-primary bg-surface-primary focus:outline-none focus:ring-1 focus:ring-primary mb-1"
                            autoFocus
                        />
                        <ScrollableShadows innerClassName="overflow-y-auto" direction="vertical" styledScrollbars>
                            <Combobox.List className="flex flex-col gap-1">
                                {(group: DataGroup) => (
                                    <Combobox.Group
                                        key={group.value}
                                        items={group.items}
                                        className="flex flex-col gap-px"
                                    >
                                        <Combobox.GroupLabel className="px-2 py-1 text-xs font-medium text-muted sticky top-0 bg-surface-primary z-10">
                                            {group.value}
                                        </Combobox.GroupLabel>
                                        <Combobox.Collection>
                                            {(item: DataItem) => (
                                                <Combobox.Item
                                                    key={item.id}
                                                    value={item}
                                                    className={menuItemStyles}
                                                    onClick={() => {
                                                        router.actions.push(item.href)
                                                        setOpen(false)
                                                    }}
                                                    render={
                                                        <ButtonPrimitive menuItem>
                                                            {item.icon}
                                                            <span className="flex-1">{item.label}</span>
                                                        </ButtonPrimitive>
                                                    }
                                                />
                                            )}
                                        </Combobox.Collection>
                                    </Combobox.Group>
                                )}
                            </Combobox.List>
                            <Combobox.Empty className="px-2 py-4 text-center text-sm text-muted empty:hidden">
                                No items found.
                            </Combobox.Empty>
                        </ScrollableShadows>
                    </Combobox.Popup>
                </Combobox.Positioner>
            </Combobox.Portal>
        </Combobox.Root>
    )
}
