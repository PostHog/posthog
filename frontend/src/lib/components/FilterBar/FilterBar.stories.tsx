import { Meta, StoryObj } from '@storybook/react'
import { useMemo, useState } from 'react'

import { IconCircleDashed, IconCheckCircle, IconClock, IconPerson, IconWarning, IconX } from '@posthog/icons'

import { FilterPickerNode, FilterPickerToken } from '../FilterPicker'
import { FilterBar, FilterBarSortOption, SortDirection } from './FilterBar'

const meta: Meta<typeof FilterBar> = {
    title: 'Filters/Filter Bar',
    component: FilterBar,
    parameters: {
        testOptions: { include3000: true },
    },
}
export default meta

type Story = StoryObj<typeof FilterBar>

const SORT_OPTIONS: FilterBarSortOption[] = [
    { value: 'last_seen', label: 'Last seen' },
    { value: 'first_seen', label: 'First seen' },
    { value: 'occurrences', label: 'Occurrences' },
    { value: 'users', label: 'Users affected' },
]

const ISSUE_SECTION = { id: 'issue', label: 'Issue', icon: <IconWarning /> }
const PERSON_SECTION = { id: 'person', label: 'Person', icon: <IconPerson /> }
const TIME_SECTION = { id: 'time', label: 'Time', icon: <IconClock /> }

function token(id: string, parts: string[], editPath: string[], onRemove: () => void): FilterPickerToken {
    return {
        id,
        editPath: { nodeIds: editPath },
        onRemove,
        parts: parts.map((part, index) => ({
            key: `${id}-${index}`,
            kind: index === 1 ? 'operator' : 'text',
            label: part,
        })),
    }
}

function useStoryFilterRoot(): {
    rootNodes: FilterPickerNode[]
    tokens: FilterPickerToken[]
    setStatus: (status: string | null) => void
    setAssignee: (assignee: string | null) => void
    setLastSeen: (lastSeen: string | null) => void
} {
    const [status, setStatus] = useState<string | null>('Active')
    const [assignee, setAssignee] = useState<string | null>('Jane Cooper')
    const [lastSeen, setLastSeen] = useState<string | null>('Last 24 hours')

    const rootNodes = useMemo<FilterPickerNode[]>(() => {
        const statuses = [
            { value: 'Active', icon: <IconCircleDashed /> },
            { value: 'Resolved', icon: <IconCheckCircle /> },
            { value: 'Suppressed', icon: <IconX /> },
        ]
        const assignees = ['Jane Cooper', 'Wade Warren', 'Product engineers']
        const timeValues = ['Last hour', 'Last 24 hours', 'Last 7 days', 'Last 30 days']

        return [
            {
                id: 'status',
                label: 'Status',
                section: ISSUE_SECTION,
                kind: 'branch',
                searchPlaceholder: 'Search statuses…',
                getChildren: ({ query }) => ({
                    isLoading: false,
                    nodes: statuses
                        .filter((option) => option.value.toLowerCase().includes(query.toLowerCase()))
                        .map((option) => ({
                            id: `status:${option.value}`,
                            label: option.value,
                            hint: 'State',
                            kind: 'action',
                            onSelect: ({ close }) => {
                                setStatus(option.value)
                                close()
                            },
                        })),
                }),
            },
            {
                id: 'assignee',
                label: 'Assignee',
                section: PERSON_SECTION,
                kind: 'branch',
                searchPlaceholder: 'Search assignees…',
                getChildren: ({ query }) => ({
                    isLoading: false,
                    nodes: assignees
                        .filter((name) => name.toLowerCase().includes(query.toLowerCase()))
                        .map((name) => ({
                            id: `assignee:${name}`,
                            label: name,
                            hint: name === 'Product engineers' ? 'Role' : 'User',
                            kind: 'action',
                            onSelect: ({ close }) => {
                                setAssignee(name)
                                close()
                            },
                        })),
                }),
            },
            {
                id: 'last-seen',
                label: 'Last seen',
                section: TIME_SECTION,
                kind: 'branch',
                searchPlaceholder: 'Choose a time filter…',
                getChildren: ({ query }) => ({
                    isLoading: false,
                    nodes: timeValues
                        .filter((value) => value.toLowerCase().includes(query.toLowerCase()))
                        .map((value) => ({
                            id: `last-seen:${value}`,
                            label: value,
                            hint: 'Shortcut',
                            kind: 'action',
                            onSelect: ({ close }) => {
                                setLastSeen(value)
                                close()
                            },
                        })),
                }),
            },
        ]
    }, [])

    const tokens = [
        ...(status ? [token(`status:${status}`, ['Status', '=', status], ['status'], () => setStatus(null))] : []),
        ...(assignee
            ? [token(`assignee:${assignee}`, ['Assignee', '=', assignee], ['assignee'], () => setAssignee(null))]
            : []),
        ...(lastSeen
            ? [token(`last-seen:${lastSeen}`, ['Last seen', '=', lastSeen], ['last-seen'], () => setLastSeen(null))]
            : []),
    ]

    return { rootNodes, tokens, setStatus, setAssignee, setLastSeen }
}

function Template({
    manyTokens = false,
    disabled = false,
    loading = false,
    longValues = false,
}: {
    manyTokens?: boolean
    disabled?: boolean
    loading?: boolean
    longValues?: boolean
}): JSX.Element {
    const { rootNodes, tokens, setStatus } = useStoryFilterRoot()
    const [dateFrom, setDateFrom] = useState<string | null>('-7d')
    const [dateTo, setDateTo] = useState<string | null>(null)
    const [sortValue, setSortValue] = useState('last_seen')
    const [sortDirection, setSortDirection] = useState<SortDirection>('DESC')

    const displayTokens = [...tokens]
    if (manyTokens) {
        displayTokens.push(
            token('priority:high', ['Priority', '=', 'High'], ['status'], () => {}),
            token('source:web', ['Source', '=', 'Browser'], ['status'], () => {}),
            token('release:latest', ['Release', '=', '2026.06.20'], ['status'], () => {})
        )
    }
    if (longValues) {
        displayTokens.push(
            token(
                'message:long',
                [
                    'Exception message',
                    '∋',
                    'A very long error message value that should truncate cleanly in the toolbar',
                ],
                ['status'],
                () => {}
            )
        )
    }

    return (
        <div className="max-w-[760px] p-4">
            <FilterBar
                pickerRootNodes={rootNodes}
                pickerTokens={displayTokens}
                reloadConfig={{ onReload: () => setStatus('Active'), loading }}
                dateConfig={{
                    dateFrom,
                    dateTo,
                    onDateChange: (from, to) => {
                        setDateFrom(from)
                        setDateTo(to)
                    },
                }}
                sortConfig={{
                    options: SORT_OPTIONS,
                    value: sortValue,
                    direction: sortDirection,
                    onChange: (value, direction) => {
                        setSortValue(value)
                        setSortDirection(direction)
                    },
                }}
                disabledReason={disabled ? 'Filters are disabled while data loads' : undefined}
                loading={loading}
            />
        </div>
    )
}

export const BareToolbar: Story = {
    render: () => <Template />,
    parameters: {
        docs: { description: { story: 'Reload, date, sort, and add-filter controls using generic picker nodes.' } },
    },
}

export const MultipleTokensWrapping: Story = {
    render: () => <Template manyTokens />,
}

export const EditableTokenFlow: Story = {
    render: () => <Template />,
    parameters: {
        docs: {
            description: {
                story: 'Click a token to open the same picker at its edit path. The back affordance returns to root; the path pill clears search and resets to root. The remove segment does not open edit.',
            },
        },
    },
}

export const DisabledAndLoadingStates: Story = {
    render: () => <Template disabled loading />,
}

export const LongTokenValues: Story = {
    render: () => <Template longValues />,
}

export const FilterOnly: Story = {
    render: () => {
        const { rootNodes, tokens } = useStoryFilterRoot()
        return (
            <div className="p-4">
                <FilterBar pickerRootNodes={rootNodes} pickerTokens={tokens} />
            </div>
        )
    },
}
