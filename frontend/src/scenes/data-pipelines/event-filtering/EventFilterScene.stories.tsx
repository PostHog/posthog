import type { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

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
        // Pin "now" so the metrics chart's default `-7d` window — and any
        // other date-derived UI — is stable across snapshot runs.
        mockDate: '2026-05-25',
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

// `EventFilterMetrics` doesn't hit `/event_filter/metrics/`; it goes through
// `appMetricsLogic`, which posts HogQL queries to `/query/HogQLQuery/`. The
// time-series query returns rows shaped `[dates, breakdown, totals]` and the
// totals query returns rows shaped `[total, ...breakdowns]`. Both are fired
// on mount, plus a separate previous-period time-series call.
//
// In live mode only `dropped` accumulates; in dry-run mode only
// `would_be_dropped` accumulates (events match the filter but are not
// actually dropped). The mocks below mirror that based on the form mode.

const METRIC_DATES = [
    '2026-05-18T00:00:00Z',
    '2026-05-19T00:00:00Z',
    '2026-05-20T00:00:00Z',
    '2026-05-21T00:00:00Z',
    '2026-05-22T00:00:00Z',
    '2026-05-23T00:00:00Z',
    '2026-05-24T00:00:00Z',
]
const METRIC_VALUES = [120, 95, 140, 110, 130, 105, 150]
const METRIC_ZEROS = [0, 0, 0, 0, 0, 0, 0]
const METRIC_TOTAL = METRIC_VALUES.reduce((sum, v) => sum + v, 0)

const EMPTY_TIMESERIES_RESULTS: unknown[][] = []
const EMPTY_TOTALS_RESULTS: unknown[][] = []

function metricsHandler(
    timeSeriesResults: unknown[][],
    totalsResults: unknown[][]
): (req: { json: () => Promise<unknown> }) => Promise<[number, unknown]> {
    return async (req) => {
        const body = (await req.json()) as { query?: { query?: string } }
        const isTimeSeries = body.query?.query?.includes('calendar') ?? false
        return [200, { results: isTimeSeries ? timeSeriesResults : totalsResults }]
    }
}

function metricsForMode(mode: 'live' | 'dry_run'): {
    timeSeries: unknown[][]
    totals: unknown[][]
} {
    const isLive = mode === 'live'
    return {
        timeSeries: [
            [METRIC_DATES, 'dropped', isLive ? METRIC_VALUES : METRIC_ZEROS],
            [METRIC_DATES, 'would_be_dropped', isLive ? METRIC_ZEROS : METRIC_VALUES],
        ],
        totals: [
            [isLive ? METRIC_TOTAL : 0, 'dropped'],
            [isLive ? 0 : METRIC_TOTAL, 'would_be_dropped'],
        ],
    }
}

function withFilter(overrides: Record<string, unknown> = {}): () => JSX.Element {
    return () => {
        useStorybookMocks({
            get: {
                '/api/environments/:team_id/event_filter/': { ...SIMPLE_FILTER, ...overrides },
            },
            post: {
                '/api/environments/:team_id/query/:kind/': metricsHandler(
                    EMPTY_TIMESERIES_RESULTS,
                    EMPTY_TOTALS_RESULTS
                ),
            },
        })
        return <App />
    }
}

function withFilterAndMetrics(overrides: Record<string, unknown> = {}): () => JSX.Element {
    return () => {
        const mode = (overrides.mode as 'live' | 'dry_run' | undefined) ?? (SIMPLE_FILTER.mode as 'dry_run')
        const { timeSeries, totals } = metricsForMode(mode)
        useStorybookMocks({
            get: {
                '/api/environments/:team_id/event_filter/': { ...SIMPLE_FILTER, ...overrides },
            },
            post: {
                '/api/environments/:team_id/query/:kind/': metricsHandler(timeSeries, totals),
            },
        })
        return <App />
    }
}

// ============================================================
// Simple — basic visual states
// ============================================================

export const EmptyState: Story = {
    parameters: {
        docs: {
            description: {
                story: `
Initial empty state shown when no filter config exists yet (API returns 204).

Expected to show:
- Status card labelled "Filter is disabled" with no colored border
- Mode segmented button defaulting to "Disabled"
- Empty filter tree with only an "Add condition" button
- No test cases section content
- No metrics chart
                `,
            },
        },
    },
}

export const DryRunWithTests: Story = {
    render: withFilterAndMetrics(),
    parameters: {
        docs: {
            description: {
                story: `
Dry-run mode with a populated filter, four test cases, and a sample metrics series.

Expected to show:
- Status card with yellow border, label "Filter is in dry run"
- "Dry run" selected in the mode segmented button
- Filter tree: root OR containing \`event_name = "$drop_me"\` and a nested AND group with two conditions
- Four test cases, all with green "Pass" tags
- Metrics summary: "Dropped" card shows 0 (+0.0%), "Would be dropped" card shows 850
  (sum of the mocked values) — dry-run only counts matches, doesn't drop them
- The Chart.js line graph canvas underneath is intentionally blank in snapshots
  (Chart.ts overrides \`draw\` to skip rendering under the storybook test runner)
                `,
            },
        },
    },
}

export const LiveMode: Story = {
    render: withFilterAndMetrics({ mode: 'live' }),
    parameters: {
        docs: {
            description: {
                story: `
Same filter as DryRunWithTests, switched to live mode.

Expected to show:
- Status card with green border, label "Filter is active"
- "Live" selected in the mode segmented button
- Status copy "Matching events are being dropped from ingestion."
- Same tree and test cases as the dry-run story
- Metrics summary: "Dropped" card shows 850 (sum of the mocked values),
  "Would be dropped" card shows 0 — live mode actually drops, doesn't shadow-count
- The Chart.js line graph canvas underneath is intentionally blank in snapshots
  (Chart.ts overrides \`draw\` to skip rendering under the storybook test runner)
                `,
            },
        },
    },
}

export const DisabledWithConditions: Story = {
    render: withFilter({ mode: 'disabled' }),
    parameters: {
        docs: {
            description: {
                story: `
Disabled mode with a configured filter tree and test cases — captures that nothing is dropped or counted
even when the filter is fully set up.

Expected to show:
- Status card with no colored border, label "Filter is disabled"
- "Disabled" selected in the mode segmented button
- Status copy "No events are being filtered or counted."
- Filter tree and test cases still rendered (same as DryRunWithTests)
- Metrics chart renders empty (no series) — disabled mode produces no metrics
                `,
            },
        },
    },
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
    parameters: {
        docs: {
            description: {
                story: `
Smallest non-empty filter — root OR with a single condition. Used to confirm the tree renders
correctly when there is no nested group to draw.

Expected to show:
- Root OR with exactly one condition row: \`event_name = "$drop_me"\`
- Two test cases, both with green "Pass" tags
                `,
            },
        },
    },
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
    parameters: {
        docs: {
            description: {
                story: `
Root OR with an empty AND group alongside a real condition. Verifies that an empty group renders
without crashing and that \`isTreeEmpty\` does not collapse the whole tree to "no conditions".

Expected to show:
- Root OR with two rows: an empty AND group (rendered with "Add condition" / "Add group" buttons,
  no leaf rows) and \`event_name = "$drop_me"\`
- Two test cases, both with green "Pass" tags
                `,
            },
        },
    },
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
    parameters: {
        docs: {
            description: {
                story: `
Root OR containing a single NOT-wrapped condition. Covers the NOT wrapper rendering and its
inverse evaluation semantics in the test-case Pass/Fail display.

Expected to show:
- Root OR with one row: a NOT wrapper around \`distinct_id ~ "admin"\`
- Two test cases, both with green "Pass" tags (the admin user is "ingest", the regular user is "drop")
                `,
            },
        },
    },
}

export const FailingTests: Story = {
    render: withFilter({
        test_cases: [
            ...SIMPLE_FILTER.test_cases,
            { event_name: '$pageview', distinct_id: 'user-1', expected_result: 'drop' },
        ],
    }),
    parameters: {
        docs: {
            description: {
                story: `
Same SIMPLE_FILTER as DryRunWithTests with one extra test case whose expected outcome doesn't
match the tree. Captures the failing-test UI plus the "tests failing — will be saved as dry run"
hint surface.

Expected to show:
- Mode is "Dry run"; status card still yellow
- Filter tree identical to DryRunWithTests
- Five test cases: four with green "Pass" tags, one with a red "Fail" tag (the trailing
  \`$pageview / user-1\` case)
- Inline danger text "Tests failing — will be saved as dry run" only appears once the user
  attempts to switch to live (not visible here)
                `,
            },
        },
    },
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
    parameters: {
        docs: {
            description: {
                story: `
Tree exercising every node type at non-trivial depth: OR → (condition, AND → (OR → (condition, condition), NOT → condition)).

Expected to show:
- Root OR with two children: \`event_name = "$drop_me"\` and an AND group
- The AND group contains a nested OR (two conditions) and a NOT-wrapped condition
- Four test cases, all with green "Pass" tags
                `,
            },
        },
    },
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
    parameters: {
        docs: {
            description: {
                story: `
Root OR with 10 sibling conditions — stresses vertical layout and the "Add condition" button
position when there are many siblings (but still under the max).

Expected to show:
- Root OR with 10 condition rows: \`event_name = "$event_0"\` … \`$event_9\`
- "Add condition" and "Add group" buttons still enabled
- Test cases section empty
                `,
            },
        },
    },
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
    parameters: {
        docs: {
            description: {
                story: `
Filter at the EVENT_FILTER_MAX_CONDITIONS limit (20). Confirms that "Add condition" / "Add group"
are disabled and the limit hint surfaces.

Expected to show:
- Root OR with 20 condition rows alternating between \`event_name\` and \`distinct_id\` fields
- "Add condition" and "Add group" buttons rendered in their disabled state
  (hovering them surfaces "Maximum of 20 conditions reached")
- Two test cases, both with green "Pass" tags
                `,
            },
        },
    },
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
                            type: 'not',
                            child: {
                                // depth 3
                                type: 'and',
                                children: [
                                    {
                                        // depth 4 — deepest group; "Add group" disabled here
                                        type: 'and',
                                        children: [
                                            {
                                                // depth 5 — the limit
                                                type: 'condition',
                                                field: 'event_name',
                                                operator: 'exact',
                                                value: '$deepest',
                                            },
                                        ],
                                    },
                                ],
                            },
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
    parameters: {
        docs: {
            description: {
                story: `
Filter at the EVENT_FILTER_MAX_DEPTH limit (5 nesting levels). Confirms indentation, connector
lines, and the "Add group" button being rendered in its disabled state inside the deepest group.
The NOT sits at depth 2 so the deep chain still bottoms out in a group (AND at depth 4) rather
than a NOT — which is what makes the depth-limit button state observable.

Expected to show:
- Visible nesting OR → AND → NOT → AND → AND → condition (\`$deepest\`)
- Sibling \`event_name = "$shallow"\` rendered alongside the NOT at AND-depth-1
- "Add group" rendered disabled inside the depth-4 AND group (its tooltip is
  "Maximum nesting depth of 5 reached"); "Add condition" still enabled there
- Two test cases, both with green "Pass" tags: \`$shallow\` drops (matches the shallow
  sibling AND the NOT inverts the inner chain to true), \`$deepest\` ingests (NOT inverts
  to false, so the AND short-circuits)
                `,
            },
        },
    },
}

export const ManyTestCases: Story = {
    render: withFilter({
        test_cases: Array.from({ length: 20 }, (_, i) => ({
            event_name: i % 2 === 0 ? '$drop_me' : '$pageview',
            distinct_id: `user-${i}`,
            expected_result: i % 2 === 0 ? ('drop' as const) : ('ingest' as const),
        })),
    }),
    parameters: {
        docs: {
            description: {
                story: `
Same SIMPLE_FILTER tree with 20 test cases — stresses the test cases list layout and scrolling.

Expected to show:
- Filter tree identical to DryRunWithTests
- 20 test case rows, alternating \`$drop_me\` and \`$pageview\`, all with green "Pass" tags
                `,
            },
        },
    },
}

// ============================================================
// Interactive — play functions that simulate user actions
// ============================================================

export const AddConditionAndTestCase: Story = {
    render: withFilter(),
    parameters: {
        docs: {
            description: {
                story: `
Adds a condition to the root OR group and a new test case via the UI.

Expected to show:
- 4 value inputs in the tree (3 original + 1 new containing "$new_event")
- 5 test cases (4 original + 1 new)
- New test case's event name is "$new_event"
- New test case shows a green "Pass" tag (matches the OR condition)
                `,
            },
        },
    },
    play: async () => {
        // Wait for the API mock to load the tree — `add-condition-root` is present
        // immediately on mount with an empty default tree, so we must wait for the
        // loaded conditions or `afterMount` will overwrite our edits mid-play.
        await waitFor(() => {
            if (!document.querySelector('input[value="$drop_me"]')) {
                throw new Error('Tree not loaded')
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

export const SwitchModeToDryRun: Story = {
    render: withFilter({ mode: 'disabled' }),
    parameters: {
        docs: {
            description: {
                story: `
Starts in disabled mode, then clicks the "Dry run" button.

Expected to show:
- Status card says "Filter is in dry run"
- Status card has the warning (yellow) border
- "Dry run" is selected in the segmented button
                `,
            },
        },
    },
    play: async () => {
        // Wait for the API mock to load the tree — otherwise `afterMount` can resolve
        // after our click and overwrite the mode back to "disabled".
        await waitFor(() => {
            if (!document.querySelector('input[value="$drop_me"]')) {
                throw new Error('Tree not loaded')
            }
        })

        Array.from(document.querySelectorAll('button'))
            .find((b) => b.textContent?.trim() === 'Dry run')!
            .click()
    },
}

export const FixFailingTestAndGoLive: Story = {
    parameters: {
        docs: {
            description: {
                story: `
Starts with a failing test case ("$dro" expected to drop, but the filter is \`contains "drop"\`),
fixes it by appending "p" to make "$drop", then clicks Live.

Expected to show:
- Status card says "Filter is active" with green border
- "Live" is selected in the segmented button
- Both test cases show green "Pass" tags (no red Fail tags)
- Second test case event name is "$drop" (was "$dro", "p" appended)
                `,
            },
        },
    },
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
            },
            post: {
                '/api/environments/:team_id/query/:kind/': metricsHandler(
                    EMPTY_TIMESERIES_RESULTS,
                    EMPTY_TOTALS_RESULTS
                ),
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

export const OpenAsciiModal: Story = {
    render: withFilter(),
    parameters: {
        docs: {
            description: {
                story: `
Clicks "Show as ASCII" to open the expression preview modal.

Expected to show:
- Modal is open with title "Filter tree"
- Modal shows the tree with "├──" and "└──" connectors
- Tree contains "$drop_me", "$internal", "bot-"
- OR at the root, AND as the nested group
                `,
            },
        },
    },
    play: async () => {
        // Wait for the API mock to load the tree before opening the modal — otherwise
        // the snapshot can capture the modal rendered over the still-empty default tree.
        await waitFor(() => {
            if (!document.querySelector('input[value="$drop_me"]')) {
                throw new Error('Tree not loaded')
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

export const RemoveConditionAndAddGroup: Story = {
    render: withFilter(),
    parameters: {
        docs: {
            description: {
                story: `
Removes the \`$drop_me\` condition, adds a new empty AND group at the root, then opens the
ASCII modal to verify the resulting structure.

Expected to show:
- \`$drop_me\` condition is gone from the tree
- Tree has 2 children in root OR: the original AND group + the new empty AND group
- ASCII modal is open showing the tree structure
- ASCII output contains "$internal", "bot-", and two AND groups
                `,
            },
        },
    },
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

export const BuildFilterFromScratch: Story = {
    render: () => {
        // 204 makes afterMount short-circuit, so the form keeps its defaults
        // (empty OR, no test cases, disabled mode) and the play function can
        // build the tree without racing the API load.
        useStorybookMocks({
            get: {
                '/api/environments/:team_id/event_filter/': () => [204, null],
            },
            post: {
                '/api/environments/:team_id/query/:kind/': metricsHandler(
                    EMPTY_TIMESERIES_RESULTS,
                    EMPTY_TOTALS_RESULTS
                ),
            },
        })
        return <App />
    },
    parameters: {
        docs: {
            description: {
                story: `
Starts from an empty filter and uses the UI to add one condition and one test case.

Expected to show:
- Tree has 1 condition: \`event_name = "$autocapture"\`
- 1 test case with event name "$autocapture"
- Test case shows a green "Pass" tag (default expected is "drop", matches the condition)
- Mode is still "Disabled"
                `,
            },
        },
    },
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
