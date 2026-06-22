import { Meta, StoryObj } from '@storybook/react'
import { ReactNode, useMemo, useState } from 'react'

import { IconBrackets, IconClock, IconDatabase, IconPerson } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { PropertyFilterType, PropertyOperator, PropertyType } from '~/types'

import { createPropertyFilterPickerNodes, createPropertyFilterToken } from './adapters'
import { FilterPicker } from './FilterPicker'
import { FilterPickerNode, FilterPickerToken } from './FilterPicker.types'
import { FilterPickerTokenPill } from './FilterPickerTokenPill'

const meta: Meta<typeof FilterPicker> = {
    title: 'Filters/Filter Picker',
    component: FilterPicker,
    parameters: {
        testOptions: { include3000: true },
    },
}
export default meta

type Story = StoryObj<typeof FilterPicker>

const issueSection = { id: 'issue', label: 'Issue', icon: <IconBrackets /> }
const personSection = { id: 'person', label: 'Person', icon: <IconPerson /> }
const propertySection = { id: 'property', label: 'Properties', icon: <IconDatabase /> }

const valueOptions = [
    'Critical',
    'High',
    'Medium',
    'Low',
    'A very long property value that should truncate in narrow menus',
]

function matching(nodes: FilterPickerNode[], query: string): FilterPickerNode[] {
    const trimmed = query.trim().toLowerCase()
    return trimmed ? nodes.filter((node) => String(node.label).toLowerCase().includes(trimmed)) : nodes
}

function propertyNode(onSelect: (label: string) => void): FilterPickerNode {
    return {
        id: 'property.severity',
        label: 'Exception severity with a very long display name',
        tokenLabel: 'Severity',
        kind: 'branch',
        section: propertySection,
        searchPlaceholder: 'Choose an operator…',
        getChildren: ({ query }) => ({
            isLoading: false,
            nodes: matching(
                [
                    {
                        id: 'property.severity.equals',
                        label: 'equals',
                        tokenLabel: '=',
                        kind: 'branch',
                        searchPlaceholder: 'Search or type a value…',
                        getChildren: ({ query: valueQuery }) => ({
                            isLoading: false,
                            hasMore: true,
                            loadMore: () => {},
                            nodes: matching(
                                valueOptions.map((label) => ({
                                    id: `property.severity.equals.${label}`,
                                    label,
                                    kind: 'action' as const,
                                    onSelect: ({ close }) => {
                                        onSelect(label)
                                        close()
                                    },
                                })),
                                valueQuery
                            ),
                        }),
                    },
                    {
                        id: 'property.severity.is-set',
                        label: 'is set',
                        tokenLabel: '∃',
                        kind: 'action',
                        onSelect: ({ close }) => {
                            onSelect('is set')
                            close()
                        },
                    },
                ],
                query
            ),
        }),
    }
}

function baseNodes(onSelect: (label: string) => void): FilterPickerNode[] {
    return [
        {
            id: 'status',
            label: 'Status',
            kind: 'branch',
            section: issueSection,
            searchPlaceholder: 'Search statuses…',
            getChildren: ({ query }) => ({
                isLoading: false,
                nodes: matching(
                    ['Active', 'Resolved', 'Suppressed'].map((label) => ({
                        id: `status.${label.toLowerCase()}`,
                        label,
                        kind: 'action' as const,
                        onSelect: ({ close }) => {
                            onSelect(label)
                            close()
                        },
                    })),
                    query
                ),
            }),
        },
        {
            id: 'assignee',
            label: 'Assignee',
            kind: 'branch',
            section: personSection,
            searchPlaceholder: 'Search assignees…',
            getChildren: ({ query }) => ({
                isLoading: false,
                nodes: matching(
                    ['Jane Cooper', 'Wade Warren', 'Product engineers'].map((label) => ({
                        id: `assignee.${label}`,
                        label,
                        hint: label === 'Product engineers' ? 'Role' : 'User',
                        kind: 'action' as const,
                        onSelect: ({ close }) => {
                            onSelect(label)
                            close()
                        },
                    })),
                    query
                ),
            }),
        },
        propertyNode(onSelect),
    ]
}

function Trigger({ children }: { children?: ReactNode }): JSX.Element {
    return <Button variant="outline">{children ?? 'Add filter'}</Button>
}

function Sandbox({ narrow = false }: { narrow?: boolean }): JSX.Element {
    const [selected, setSelected] = useState('High')
    const nodes = useMemo(() => baseNodes(setSelected), [])
    const token: FilterPickerToken = {
        id: 'severity-token',
        editPath: { nodeIds: ['property.severity', 'property.severity.equals'] },
        parts: [
            { kind: 'property', label: 'Severity' },
            { kind: 'operator', label: '=' },
            { kind: 'value', label: selected },
        ],
        onRemove: () => setSelected(''),
    }

    return (
        <div className={narrow ? 'w-56 p-4' : 'p-4'}>
            <div className="mb-3 flex flex-wrap items-center gap-2">
                <FilterPicker rootNodes={nodes} trigger={<Trigger />} />
                {selected && (
                    <FilterPicker
                        rootNodes={nodes}
                        initialPath={token.editPath}
                        trigger={<FilterPickerTokenPill token={token} onEdit={() => {}} />}
                    />
                )}
            </div>
            <div className="text-xs text-tertiary">Selected value: {selected || 'none'}</div>
        </div>
    )
}

export const RootWithSections: Story = {
    render: () => <Sandbox />,
}

export const NestedPropertyOperatorValue: Story = {
    render: () => <Sandbox />,
}

export const CustomPanel: Story = {
    render: () => {
        const nodes: FilterPickerNode[] = [
            {
                id: 'date',
                label: 'Date',
                kind: 'panel',
                section: { id: 'time', label: 'Time', icon: <IconClock /> },
                renderPanel: ({ close }) => (
                    <div className="flex flex-col gap-2 p-2">
                        <div className="text-sm font-semibold">Pick a date range</div>
                        <Button size="sm" onClick={close}>
                            Last 24 hours
                        </Button>
                        <Button size="sm" onClick={close}>
                            Last 7 days
                        </Button>
                    </div>
                ),
            },
        ]
        return (
            <div className="p-4">
                <FilterPicker rootNodes={nodes} trigger={<Trigger />} />
            </div>
        )
    },
}

export const LoadingAndEmpty: Story = {
    render: () => {
        const nodes: FilterPickerNode[] = [
            {
                id: 'loading',
                label: 'Loading branch',
                kind: 'branch',
                getChildren: () => ({ isLoading: true, nodes: [] }),
            },
            {
                id: 'empty',
                label: 'Empty branch',
                kind: 'branch',
                getChildren: () => ({ isLoading: false, nodes: [], emptyMessage: 'Nothing here yet' }),
            },
        ]
        return (
            <div className="p-4">
                <FilterPicker rootNodes={nodes} trigger={<Trigger />} />
            </div>
        )
    },
}

export const EditableTokenPath: Story = {
    parameters: {
        docs: {
            description: {
                story: 'Keyboard-only flow: open the token, type to search the scoped value list, use ArrowDown to move into results, Backspace/Tab normally, and the path pill reset returns to the root.',
            },
        },
    },
    render: () => <Sandbox />,
}

export const LongLabelsAndNarrowWidths: Story = {
    render: () => <Sandbox narrow />,
}

export const PropertyFilterAdapter: Story = {
    render: () => {
        const [token, setToken] = useState<FilterPickerToken | null>(null)
        const valueOptions = useMemo(
            () => ['Chrome', 'Safari', 'Firefox', 'Mobile app'].map((label) => ({ label, value: label })),
            []
        )
        const rootNodes = useMemo(
            () =>
                createPropertyFilterPickerNodes({
                    properties: [
                        {
                            key: '$browser',
                            label: 'Browser',
                            type: PropertyFilterType.Event,
                            propertyType: PropertyType.String,
                            description: 'Event property',
                        },
                        {
                            key: 'plan',
                            label: 'Plan',
                            type: PropertyFilterType.Person,
                            propertyType: PropertyType.String,
                            description: 'Person property',
                        },
                        {
                            key: 'id',
                            label: 'Cohort',
                            type: PropertyFilterType.Cohort,
                            propertyType: PropertyType.Cohort,
                            description: 'Cohorts use the same token model',
                        },
                        {
                            key: 'beta-checkout',
                            label: 'Feature flag',
                            type: PropertyFilterType.Flag,
                            propertyType: PropertyType.Flag,
                            description: 'Feature flags use the same token model',
                        },
                    ],
                    rootSections: {
                        [PropertyFilterType.Event]: propertySection,
                        [PropertyFilterType.Person]: personSection,
                        [PropertyFilterType.Cohort]: personSection,
                        [PropertyFilterType.Flag]: personSection,
                    },
                    operatorAllowlist: {
                        [PropertyType.String]: [
                            PropertyOperator.Exact,
                            PropertyOperator.IContains,
                            PropertyOperator.IsSet,
                        ],
                        [PropertyType.Cohort]: [PropertyOperator.In, PropertyOperator.NotIn],
                        [PropertyType.Flag]: [PropertyOperator.FlagEvaluatesTo],
                    },
                    valueLoader: ({ property, query }) => {
                        if (property.type === PropertyFilterType.Cohort) {
                            return {
                                values: [
                                    { label: 'Power users', value: 1 },
                                    { label: 'Recently active', value: 2 },
                                ],
                            }
                        }
                        if (property.type === PropertyFilterType.Flag) {
                            return {
                                values: [
                                    { label: 'true', value: true },
                                    { label: 'false', value: false },
                                ],
                            }
                        }
                        return {
                            values: valueOptions.filter((option) =>
                                option.label.toLowerCase().includes(query.toLowerCase())
                            ),
                            allowCustomValues: true,
                            hasMore: true,
                            loadMore: () => {},
                        }
                    },
                    eventNames: ['$exception'],
                    onSelect: (filter, { close }) => {
                        setToken(
                            createPropertyFilterToken(filter, {
                                editNodeIds: [
                                    `property:${filter.type}:${filter.key}`,
                                    `property:${filter.type}:${filter.key}:operator:${'operator' in filter ? filter.operator : PropertyOperator.Exact}`,
                                ],
                                onRemove: () => setToken(null),
                            })
                        )
                        close()
                    },
                }),
            [valueOptions]
        )

        return (
            <div className="flex flex-col gap-3 p-4">
                <FilterPicker rootNodes={rootNodes} trigger={<Trigger />} />
                {token ? <FilterPickerTokenPill token={token} onEdit={() => {}} /> : null}
            </div>
        )
    },
}

export const LoadMoreState: Story = {
    render: () => {
        const [visibleCount, setVisibleCount] = useState(3)
        const nodes: FilterPickerNode[] = [
            {
                id: 'feature-flag',
                label: 'Feature flag',
                kind: 'branch',
                getChildren: () => ({
                    nodes: Array.from({ length: visibleCount }, (_, index) => ({
                        id: `flag-${index}`,
                        label: `Feature flag ${index + 1}`,
                        kind: 'action' as const,
                    })),
                    hasMore: visibleCount < 9,
                    loadMore: () => setVisibleCount((count) => Math.min(count + 3, 9)),
                }),
            },
        ]

        return (
            <div className="p-4">
                <FilterPicker rootNodes={nodes} trigger={<Trigger />} />
            </div>
        )
    },
}

export const UnresolvedEditPathFallback: Story = {
    render: () => (
        <div className="flex flex-col gap-2 p-4">
            <FilterPicker
                rootNodes={baseNodes(() => {})}
                initialPath={{ nodeIds: ['property.severity', 'missing-operator'] }}
                trigger={
                    <FilterPickerTokenPill
                        token={{
                            id: 'stale-token',
                            parts: [
                                { kind: 'property', label: 'Severity' },
                                { kind: 'operator', label: '=' },
                                { kind: 'value', label: 'Deleted value' },
                            ],
                        }}
                    />
                }
            />
            <div className="text-xs text-tertiary">
                A stale edit path falls back to the root picker instead of opening a broken level.
            </div>
        </div>
    ),
}
