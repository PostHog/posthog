import type { Meta, StoryObj } from '@storybook/react'
import { userEvent, waitFor } from '@storybook/testing-library'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'

type Story = StoryObj<typeof App>

const meta: Meta<typeof App> = {
    title: 'Scenes-App/Data Pipelines/Event Filtering',
    component: App,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        pageUrl: urls.eventFiltering(),
        testOptions: {
            waitForLoadersToDisappear: true,
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/event_filter/': () => [204, null],
            },
        }),
    ],
}
export default meta

// --- Mock data ---

const MOCK_ID = '019d6fed-835f-0000-a4e7-c2d7026252b4'

const SIMPLE_FILTER = {
    id: MOCK_ID,
    mode: 'dry_run',
    filter_tree: {
        type: 'or',
        children: [
            { type: 'condition', field: 'event_name', operator: 'exact', value: '$drop_me' },
            {
                type: 'and',
                children: [
                    { type: 'condition', field: 'event_name', operator: 'exact', value: '$internal' },
                    { type: 'condition', field: 'distinct_id', operator: 'contains', value: 'bot-' },
                ],
            },
        ],
    },
    test_cases: [
        { event_name: '$drop_me', distinct_id: 'user-1', expected_result: 'drop' },
        { event_name: '$internal', distinct_id: 'bot-crawler', expected_result: 'drop' },
        { event_name: '$internal', distinct_id: 'real-user', expected_result: 'ingest' },
        { event_name: '$pageview', distinct_id: 'user-1', expected_result: 'ingest' },
    ],
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
}

const EMPTY_METRICS = { labels: [], series: [] }
const EMPTY_TOTALS = { totals: {} }

const SAMPLE_METRICS = {
    labels: ['2024-01-01', '2024-01-02', '2024-01-03', '2024-01-04', '2024-01-05'],
    series: [
        { name: 'dropped', values: [120, 95, 140, 110, 130] },
        { name: 'would_be_dropped', values: [0, 0, 0, 0, 0] },
    ],
}

function withFilter(overrides: Record<string, unknown> = {}): () => JSX.Element {
    return () => {
        useStorybookMocks({
            get: {
                '/api/environments/:team_id/event_filter/': { ...SIMPLE_FILTER, ...overrides },
                '/api/environments/:team_id/event_filter/metrics/': EMPTY_METRICS,
                '/api/environments/:team_id/event_filter/metrics/totals/': EMPTY_TOTALS,
            },
        })
        return <App />
    }
}

function withFilterAndMetrics(overrides: Record<string, unknown> = {}): () => JSX.Element {
    return () => {
        useStorybookMocks({
            get: {
                '/api/environments/:team_id/event_filter/': { ...SIMPLE_FILTER, ...overrides },
                '/api/environments/:team_id/event_filter/metrics/': SAMPLE_METRICS,
                '/api/environments/:team_id/event_filter/metrics/totals/': EMPTY_TOTALS,
            },
        })
        return <App />
    }
}

// ============================================================
// Simple — basic visual states
// ============================================================

export const EmptyState: Story = {}

export const DryRunWithTests: Story = {
    render: withFilterAndMetrics(),
}

export const LiveMode: Story = {
    render: withFilterAndMetrics({ mode: 'live' }),
}

export const DisabledWithConditions: Story = {
    render: withFilter({ mode: 'disabled' }),
}

// ============================================================
// Edge cases
// ============================================================

export const SingleCondition: Story = {
    render: withFilter({
        filter_tree: {
            type: 'or',
            children: [{ type: 'condition', field: 'event_name', operator: 'exact', value: '$drop_me' }],
        },
        test_cases: [
            { event_name: '$drop_me', distinct_id: 'user-1', expected_result: 'drop' },
            { event_name: '$pageview', distinct_id: 'user-1', expected_result: 'ingest' },
        ],
    }),
}

export const EmptyGroupsInTree: Story = {
    render: withFilter({
        filter_tree: {
            type: 'or',
            children: [
                { type: 'and', children: [] },
                { type: 'condition', field: 'event_name', operator: 'exact', value: '$drop_me' },
            ],
        },
        test_cases: [
            { event_name: '$drop_me', distinct_id: 'user-1', expected_result: 'drop' },
            { event_name: '$pageview', distinct_id: 'user-1', expected_result: 'ingest' },
        ],
    }),
}

export const NotWrappedCondition: Story = {
    render: withFilter({
        filter_tree: {
            type: 'or',
            children: [
                {
                    type: 'not',
                    child: { type: 'condition', field: 'distinct_id', operator: 'contains', value: 'admin' },
                },
            ],
        },
        test_cases: [
            { event_name: '$pageview', distinct_id: 'admin-user', expected_result: 'ingest' },
            { event_name: '$pageview', distinct_id: 'regular-user', expected_result: 'drop' },
        ],
    }),
}

export const FailingTests: Story = {
    render: withFilter({
        test_cases: [
            ...SIMPLE_FILTER.test_cases,
            { event_name: '$pageview', distinct_id: 'user-1', expected_result: 'drop' },
        ],
    }),
}

export const DeepNestedTree: Story = {
    render: withFilter({
        filter_tree: {
            type: 'or',
            children: [
                { type: 'condition', field: 'event_name', operator: 'exact', value: '$drop_me' },
                {
                    type: 'and',
                    children: [
                        {
                            type: 'or',
                            children: [
                                { type: 'condition', field: 'event_name', operator: 'exact', value: '$internal' },
                                { type: 'condition', field: 'event_name', operator: 'contains', value: 'bot_' },
                            ],
                        },
                        {
                            type: 'not',
                            child: { type: 'condition', field: 'distinct_id', operator: 'exact', value: 'admin-user' },
                        },
                    ],
                },
            ],
        },
        test_cases: [
            { event_name: '$drop_me', distinct_id: 'anyone', expected_result: 'drop' },
            { event_name: '$internal', distinct_id: 'user-1', expected_result: 'drop' },
            { event_name: '$internal', distinct_id: 'admin-user', expected_result: 'ingest' },
            { event_name: '$pageview', distinct_id: 'user-1', expected_result: 'ingest' },
        ],
    }),
}

export const ManyConditions: Story = {
    render: withFilter({
        filter_tree: {
            type: 'or',
            children: Array.from({ length: 10 }, (_, i) => ({
                type: 'condition' as const,
                field: 'event_name' as const,
                operator: 'exact' as const,
                value: `$event_${i}`,
            })),
        },
        test_cases: [],
    }),
}

export const AtMaxConditions: Story = {
    render: withFilter({
        filter_tree: {
            type: 'or',
            children: Array.from({ length: 20 }, (_, i) => ({
                type: 'condition' as const,
                field: i % 2 === 0 ? ('event_name' as const) : ('distinct_id' as const),
                operator: 'exact' as const,
                value: `$event_${i}`,
            })),
        },
        test_cases: [
            { event_name: '$event_0', distinct_id: 'user-1', expected_result: 'drop' },
            { event_name: '$nomatch', distinct_id: 'user-1', expected_result: 'ingest' },
        ],
    }),
}

export const AtMaxDepth: Story = {
    render: withFilter({
        filter_tree: {
            type: 'or',
            children: [
                {
                    // depth 1
                    type: 'and',
                    children: [
                        {
                            // depth 2
                            type: 'or',
                            children: [
                                {
                                    // depth 3
                                    type: 'and',
                                    children: [
                                        {
                                            // depth 4
                                            type: 'not',
                                            child: {
                                                // depth 5 — the limit
                                                type: 'condition',
                                                field: 'event_name',
                                                operator: 'exact',
                                                value: '$deepest',
                                            },
                                        },
                                    ],
                                },
                            ],
                        },
                        { type: 'condition', field: 'event_name', operator: 'exact', value: '$shallow' },
                    ],
                },
            ],
        },
        test_cases: [
            { event_name: '$shallow', distinct_id: 'user-1', expected_result: 'drop' },
            { event_name: '$deepest', distinct_id: 'user-1', expected_result: 'ingest' },
        ],
    }),
}

export const ManyTestCases: Story = {
    render: withFilter({
        test_cases: Array.from({ length: 20 }, (_, i) => ({
            event_name: i % 2 === 0 ? '$drop_me' : '$pageview',
            distinct_id: `user-${i}`,
            expected_result: i % 2 === 0 ? ('drop' as const) : ('ingest' as const),
        })),
    }),
}

// ============================================================
// Interactive — play functions that simulate user actions
// ============================================================

// Verify:
// - [ ] 4 value inputs in tree (3 original + 1 new with "$new_event")
// - [ ] 5 test cases (4 original + 1 new)
// - [ ] new test case event name is "$new_event"
// - [ ] new test case shows "Pass" tag (matches the OR condition)
export const AddConditionAndTestCase: Story = {
    render: withFilter(),
    play: async () => {
        await waitFor(() => {
            if (!document.querySelector('[data-attr="add-condition-root"]')) {
                throw new Error('Tree not rendered')
            }
        })

        const inputsBefore = document.querySelectorAll('input[placeholder="Value..."]').length

        // Add a condition to the root OR
        document.querySelector<HTMLElement>('[data-attr="add-condition-root"]')!.click()

        // Wait for new input to appear
        await waitFor(() => {
            if (document.querySelectorAll('input[placeholder="Value..."]').length <= inputsBefore) {
                throw new Error('New input not added')
            }
        })

        // Fill the new condition (last Value... input)
        const condInputs = document.querySelectorAll<HTMLInputElement>('input[placeholder="Value..."]')
        const newCondInput = condInputs[condInputs.length - 1]
        await userEvent.clear(newCondInput)
        await userEvent.paste('$new_event')

        const testCasesBefore = document.querySelectorAll('input[placeholder="$pageview"]').length

        // Add a test case
        Array.from(document.querySelectorAll('button'))
            .find((b) => b.textContent?.trim() === 'Add test case')!
            .click()

        // Wait for test case input to appear
        await waitFor(() => {
            if (document.querySelectorAll('input[placeholder="$pageview"]').length <= testCasesBefore) {
                throw new Error('Test case input not added')
            }
        })

        // Fill test case event name (last $pageview input)
        const eventInputs = document.querySelectorAll<HTMLInputElement>('input[placeholder="$pageview"]')
        const newEventInput = eventInputs[eventInputs.length - 1]
        await userEvent.clear(newEventInput)
        await userEvent.paste('$new_event')
    },
}

// Verify:
// - [ ] status card says "Filter is in dry run"
// - [ ] status card has warning border
// - [ ] "Dry run" is selected in the segmented button
export const SwitchModeToDryRun: Story = {
    render: withFilter({ mode: 'disabled' }),
    play: async () => {
        await waitFor(() => {
            if (!document.querySelector('[data-attr="add-condition-root"]')) {
                throw new Error('Tree not rendered')
            }
        })

        Array.from(document.querySelectorAll('button'))
            .find((b) => b.textContent?.trim() === 'Dry run')!
            .click()
    },
}

// Verify:
// - [ ] status card says "Filter is active" with green border
// - [ ] "Live" is selected in the segmented button
// - [ ] both test cases show "Pass" tags (no red tags)
// - [ ] second test case event name is "$drop" (was "$dro", "p" appended)
export const FixFailingTestAndGoLive: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/environments/:team_id/event_filter/': {
                    ...SIMPLE_FILTER,
                    filter_tree: {
                        type: 'or',
                        children: [{ type: 'condition', field: 'event_name', operator: 'contains', value: 'drop' }],
                    },
                    test_cases: [
                        { event_name: '$drop_me', distinct_id: 'user-1', expected_result: 'drop' },
                        { event_name: '$dro', distinct_id: 'user-1', expected_result: 'drop' },
                    ],
                },
                '/api/environments/:team_id/event_filter/metrics/': EMPTY_METRICS,
                '/api/environments/:team_id/event_filter/metrics/totals/': EMPTY_TOTALS,
            },
        })
        return <App />
    },
    play: async () => {
        // Wait for the failing test
        await waitFor(
            () => {
                if (!document.querySelector('.LemonTag--danger')) {
                    throw new Error('Fail tag not rendered')
                }
            },
            { timeout: 5000 }
        )

        // Fix: append "p" to "$dro" → "$drop"
        const failingInput = document.querySelector<HTMLInputElement>('input[value="$dro"]')!
        await userEvent.type(failingInput, 'p')

        // Wait for all tests to pass
        await waitFor(() => {
            if (document.querySelector('.LemonTag--danger')) {
                throw new Error('Still has failing tests')
            }
        })

        // Click Live
        const allButtons = Array.from(document.querySelectorAll('button'))
        const liveButton = allButtons.find((b) => b.textContent?.trim() === 'Live')!
        await userEvent.click(liveButton)
    },
}

// Verify:
// - [ ] modal is open with title "Filter tree"
// - [ ] modal shows tree with "├──" and "└──" connectors
// - [ ] tree contains "$drop_me", "$internal", "bot-"
// - [ ] OR at root, AND as nested group
export const OpenAsciiModal: Story = {
    render: withFilter(),
    play: async () => {
        await waitFor(() => {
            if (!document.querySelector('[data-attr="add-condition-root"]')) {
                throw new Error('Tree not rendered')
            }
        })

        Array.from(document.querySelectorAll('button'))
            .find((b) => b.textContent?.trim() === 'Show as ASCII')!
            .click()

        await waitFor(() => {
            const modal = document.querySelector('.LemonModal pre')
            if (!modal?.textContent?.includes('├──')) {
                throw new Error('ASCII modal not rendered')
            }
        })
    },
}

// Verify:
// - [ ] $drop_me condition is gone from the tree
// - [ ] tree has 2 children in root OR: original AND group + new empty AND group
// - [ ] ASCII modal is open showing the tree structure
// - [ ] ASCII output contains "$internal", "bot-", and two AND groups
export const RemoveConditionAndAddGroup: Story = {
    render: withFilter(),
    play: async () => {
        await waitFor(() => {
            if (!document.querySelector('[data-attr="remove-0"]')) {
                throw new Error('Tree not rendered')
            }
        })

        // Remove $drop_me (path [0] in root OR)
        document.querySelector<HTMLElement>('[data-attr="remove-0"]')!.click()

        // Wait for removal — root OR should have only 1 child (no remove-1 button)
        await waitFor(() => {
            if (document.querySelector('[data-attr="remove-1"]')) {
                throw new Error('Tree still has 2+ children in root OR')
            }
        })

        // Add a group to the root OR
        document.querySelector<HTMLElement>('[data-attr="add-group-root"]')!.click()

        // Wait for new group to appear — root OR should have 2 children again
        await waitFor(() => {
            if (!document.querySelector('[data-attr="remove-1"]')) {
                throw new Error('New group not added')
            }
        })

        // Open ASCII modal to verify the tree structure
        const allButtons = Array.from(document.querySelectorAll('button'))
        const asciiButton = allButtons.find((b) => b.textContent?.trim() === 'Show as ASCII')!
        asciiButton.click()

        await waitFor(() => {
            const modal = document.querySelector('.LemonModal pre')
            if (!modal?.textContent?.includes('$internal')) {
                throw new Error('ASCII modal not rendered')
            }
        })
    },
}

// Verify:
// - [ ] tree has 1 condition: event_name = "$autocapture"
// - [ ] 1 test case with event name "$autocapture"
// - [ ] test case shows "Pass" tag (default expected is "drop", matches the condition)
// - [ ] mode is still "Disabled"
export const BuildFilterFromScratch: Story = {
    render: withFilter({
        id: null,
        mode: 'disabled',
        filter_tree: { type: 'or', children: [] },
        test_cases: [],
    }),
    play: async () => {
        await waitFor(() => {
            if (!document.querySelector('[data-attr="add-condition-root"]')) {
                throw new Error('Empty tree not rendered')
            }
        })

        // Add first condition
        document.querySelector<HTMLElement>('[data-attr="add-condition-root"]')!.click()

        // Wait for input to appear
        await waitFor(() => {
            if (!document.querySelector('input[placeholder="Value..."]')) {
                throw new Error('Value input not found')
            }
        })

        // Fill the condition value
        const valueInput = document.querySelector<HTMLInputElement>('input[placeholder="Value..."]')!
        await userEvent.clear(valueInput)
        await userEvent.paste('$autocapture')

        // Add a test case
        Array.from(document.querySelectorAll('button'))
            .find((b) => b.textContent?.trim() === 'Add test case')!
            .click()

        // Wait for test case input
        await waitFor(() => {
            if (!document.querySelector('input[placeholder="$pageview"]')) {
                throw new Error('Event input not found')
            }
        })

        // Fill test case event name
        const eventInput = document.querySelector<HTMLInputElement>('input[placeholder="$pageview"]')!
        await userEvent.clear(eventInput)
        await userEvent.paste('$autocapture')
    },
}
