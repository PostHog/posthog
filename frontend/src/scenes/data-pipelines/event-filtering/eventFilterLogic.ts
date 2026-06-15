/**
 * Kea logic for the event filtering scene.
 *
 * Manages a singleton per-team event filter config: a boolean expression tree
 * that determines which events to drop at ingestion time.
 *
 * ## User actions → logic flow
 *
 * ### Filter tree editor
 *
 * The tree editor renders the filter as nested AND/OR groups with condition
 * rows. Each group and condition receives a `path` prop (TreePath) that
 * identifies its position in the tree.
 *
 *   - Change field/operator/value → `updateTreeNode(path, newNode)`
 *   - Toggle AND ↔ OR → `updateTreeNode(path, { type: newType, children })`
 *   - "Add condition" → `addChild(path)`
 *   - "Add group" → `updateTreeNode(path, { ...node, children: [..., newGroup] })`
 *   - Trash icon → `removeChild(parentPath, childIndex)`
 *   - "Negate" → `wrapInNot(path)`
 *   - "Remove NOT" → `unwrapNot(path)`
 *
 * ### Drag and drop
 *
 * Users can drag conditions and groups to reorder or move between groups.
 * DnD is handled in the scene component using @dnd-kit, not through kea actions:
 *   - Reorder within same group → arrayMove + `updateTreeNode`
 *   - Move between groups → deep-clone, splice, `setFilterFormValue`
 *   - Drop into own descendant is blocked
 *
 * ### Mode selector
 *
 *   - Change disabled/dry_run/live → `setFilterFormValue('mode', value)`
 *   - Blocked from 'live' if test cases are failing
 *
 * ### Test cases
 *
 *   - "Add test case" → `addTestCase()`
 *   - Edit fields → `updateTestCase(index, updates)`
 *   - Trash → `removeTestCase(index)`
 *   - Pass/fail badges update via `testResults` selector (client-side evaluation)
 *
 * ### Save
 *
 *   - "Save" → `submitFilterForm()` → validation → POST to event_filter/ (upsert)
 *   - If 'live' but tests fail, auto-downgrades to 'dry_run'
 *
 * ## Evaluation parity
 *
 * evaluateFilterTree runs client-side for test case preview. Equivalent
 * implementations exist in the Django model (validation on save) and
 * the Node.js ingestion pipeline (runtime filtering).
 */
import { actions, afterMount, kea, listeners, path, selectors } from 'kea'
import { forms } from 'kea-forms'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { Breadcrumb } from '~/types'

import type { eventFilterLogicType } from './eventFilterLogicType'

// Limits — must match MAX_CONDITIONS and MAX_TREE_DEPTH in posthog/models/event_filter_config.py
export const EVENT_FILTER_MAX_CONDITIONS = 20
export const EVENT_FILTER_MAX_DEPTH = 5

// --- Filter tree types ---
// Recursive discriminated union. Mirrors the JSON schema stored in Postgres
// and the Zod schema in nodejs/src/ingestion/common/event-filters/schema.ts.

export type FilterNode = FilterConditionNode | FilterAndNode | FilterOrNode | FilterNotNode

export interface FilterConditionNode {
    type: 'condition'
    field: 'event_name' | 'distinct_id'
    operator: 'exact' | 'contains'
    value: string
}

export interface FilterAndNode {
    type: 'and'
    children: FilterNode[]
}

export interface FilterOrNode {
    type: 'or'
    children: FilterNode[]
}

export interface FilterNotNode {
    type: 'not'
    child: FilterNode
}

export interface TestCase {
    _key: string
    event_name: string
    distinct_id: string
    expected_result: 'drop' | 'ingest'
}

let testCaseCounter = 0
export function nextTestCaseKey(): string {
    return `tc${testCaseCounter++}`
}

export interface TestResult {
    actual: 'drop' | 'ingest'
    pass: boolean
}

export type EventFilterMode = 'disabled' | 'dry_run' | 'live'

export interface EventFilterFormValues {
    id: string | null
    mode: EventFilterMode
    filter_tree: FilterNode
    test_cases: TestCase[]
}

const DEFAULT_FORM: EventFilterFormValues = {
    id: null,
    mode: 'disabled',
    filter_tree: { type: 'or', children: [] },
    test_cases: [],
}

// --- Pure functions (shared across 3 implementations) ---

/**
 * Evaluate a filter tree against a test event. Returns true if the event should be dropped.
 *
 * Safety: empty AND/OR groups return false (never drop). This is intentional —
 * dropping is irreversible, so we err on the side of not dropping.
 */
export function evaluateFilterTree(node: FilterNode, event: Record<string, string>): boolean {
    switch (node.type) {
        case 'condition': {
            const fieldValue = event[node.field]
            if (fieldValue === undefined) {
                return false
            }
            switch (node.operator) {
                case 'exact':
                    return fieldValue === node.value
                case 'contains':
                    return fieldValue.includes(node.value)
            }
        }
        case 'and':
            // Guard: [].every() is true in JS, which would drop everything
            return node.children.length > 0 && node.children.every((child) => evaluateFilterTree(child, event))
        case 'or':
            return node.children.some((child) => evaluateFilterTree(child, event))
        case 'not':
            return !evaluateFilterTree(node.child, event)
    }
}

/** Returns true if the tree contains at least one condition leaf. */
export function treeHasConditions(node: FilterNode): boolean {
    switch (node.type) {
        case 'condition':
            return true
        case 'not':
            return treeHasConditions(node.child)
        case 'and':
        case 'or':
            return node.children.some((child) => treeHasConditions(child))
    }
}

/** Counts the total number of condition leaves in the tree. */
export function countConditions(node: FilterNode): number {
    switch (node.type) {
        case 'condition':
            return 1
        case 'not':
            return countConditions(node.child)
        case 'and':
        case 'or':
            return node.children.reduce((sum, child) => sum + countConditions(child), 0)
    }
}

/** Returns true if any condition leaf has an empty or whitespace-only value. */
export function treeHasEmptyValues(node: FilterNode): boolean {
    switch (node.type) {
        case 'condition':
            return !node.value || node.value.trim() === ''
        case 'not':
            return treeHasEmptyValues(node.child)
        case 'and':
        case 'or':
            return node.children.some((child) => treeHasEmptyValues(child))
    }
}

/**
 * Ensure the root is an and/or group. The editor can only add conditions or
 * groups inside a group node, and the backend prunes single-child groups — so a
 * saved one-condition filter loads back as a bare condition (or NOT) with no
 * group to host the "Add condition"/"Add group" buttons. Wrap any non-group root
 * in an OR so the add affordances are always present.
 */
export function normalizeRootToGroup(node: FilterNode): FilterNode {
    if (node.type === 'and' || node.type === 'or') {
        return node
    }
    return { type: 'or', children: [node] }
}

// --- Immutable tree updates ---

/**
 * Path into a filter tree. Numbers index into AND/OR children arrays,
 * 'child' navigates into a NOT node's inner child.
 * E.g. [0, 'child', 1] = "root.children[0].child.children[1]"
 */
export type TreePath = ('child' | number)[]

/**
 * Immutable deep update of a filter tree node at the given path.
 * Shallow-copies only the nodes along the path; unchanged subtrees
 * are shared by reference. Returns the node unchanged if the path
 * doesn't match the tree structure (e.g. numeric step on a NOT node).
 */
export function updateAtPath(node: FilterNode, path: TreePath, updater: (node: FilterNode) => FilterNode): FilterNode {
    if (path.length === 0) {
        return updater(node)
    }
    const [step, ...rest] = path
    if (typeof step === 'number' && (node.type === 'and' || node.type === 'or')) {
        return {
            ...node,
            children: node.children.map((child, i) => (i === step ? updateAtPath(child, rest, updater) : child)),
        }
    }
    if (step === 'child' && node.type === 'not') {
        return { ...node, child: updateAtPath(node.child, rest, updater) }
    }
    return node
}

// --- Kea logic ---

export const eventFilterLogic = kea<eventFilterLogicType>([
    path(['scenes', 'data-pipelines', 'event-filtering', 'eventFilterLogic']),

    actions({
        // Tree manipulation — each takes a path to the target node
        updateTreeNode: (pathKeys: TreePath, node: FilterNode) => ({ pathKeys, node }),
        wrapInNot: (pathKeys: TreePath) => ({ pathKeys }),
        unwrapNot: (pathKeys: TreePath) => ({ pathKeys }),
        addChild: (pathKeys: TreePath) => ({ pathKeys }),
        removeChild: (pathKeys: TreePath, childIndex: number) => ({ pathKeys, childIndex }),
        convertToGroup: (pathKeys: TreePath, groupType: 'and' | 'or') => ({ pathKeys, groupType }),
        // Test case management
        addTestCase: true,
        removeTestCase: (index: number) => ({ index }),
        updateTestCase: (index: number, updates: Partial<TestCase>) => ({ index, updates }),
    }),

    forms(({ values }) => ({
        filterForm: {
            defaults: DEFAULT_FORM,
            errors: ({ filter_tree, mode, test_cases }: EventFilterFormValues) => ({
                // Validation errors go on `mode` (a string field) rather than `filter_tree`
                // because kea-forms expects errors on object fields to be DeepPartialMap, not strings.
                mode: (() => {
                    if (mode !== 'disabled' && !treeHasConditions(filter_tree)) {
                        return 'Filter must have at least one condition to be activated'
                    }
                    if (treeHasConditions(filter_tree) && treeHasEmptyValues(filter_tree)) {
                        return 'All conditions must have a value'
                    }
                    if (mode === 'live' && treeHasConditions(filter_tree) && test_cases.length === 0) {
                        return 'Add at least one test case before going live'
                    }
                    return undefined
                })(),
            }),
            submit: async (formValues) => {
                const { currentTeamId } = values

                // Safety: downgrade to dry_run if tests are failing
                if (formValues.mode === 'live' && !values.allTestsPass && formValues.test_cases.length > 0) {
                    formValues = { ...formValues, mode: 'dry_run' }
                }

                // Strip _key from test cases before sending to the API
                const payload = {
                    ...formValues,
                    test_cases: formValues.test_cases.map(({ _key, ...tc }) => tc),
                }
                await api.create(`api/environments/${currentTeamId}/event_filter/`, payload)
                lemonToast.success('Event filter saved')
            },
        },
    })),

    selectors({
        currentTeamId: [() => [teamLogic.selectors.currentTeamId], (id: number) => id],

        /** Total number of condition leaves in the current tree. */
        conditionCount: [
            (s) => [s.filterForm],
            (form: EventFilterFormValues): number => countConditions(form.filter_tree),
        ],

        /** Run each test case against the current tree client-side for live preview. */
        testResults: [
            (s) => [s.filterForm],
            (form: EventFilterFormValues): TestResult[] =>
                form.test_cases.map((tc) => {
                    const dropped = evaluateFilterTree(form.filter_tree, {
                        event_name: tc.event_name,
                        distinct_id: tc.distinct_id,
                    })
                    const actual = dropped ? 'drop' : 'ingest'
                    return { actual, pass: actual === tc.expected_result }
                }),
        ],

        /** True if there are no test cases or all pass. Gates the live mode toggle. */
        allTestsPass: [
            (s) => [s.testResults, s.filterForm],
            (results: TestResult[], form: EventFilterFormValues): boolean =>
                form.test_cases.length === 0 || results.every((r) => r.pass),
        ],

        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: 'EventFiltering',
                    name: 'Event ingestion filtering',
                    iconType: 'data_pipeline',
                },
            ],
        ],
    }),

    // Each listener produces a new immutable tree and updates the form.
    // All tree mutations go through updateAtPath to preserve structural sharing.
    listeners(({ actions, values }) => ({
        updateTreeNode: ({ pathKeys, node }) => {
            const newTree = updateAtPath(values.filterForm.filter_tree, pathKeys, () => node)
            actions.setFilterFormValue('filter_tree', newTree)
        },
        wrapInNot: ({ pathKeys }) => {
            const newTree = updateAtPath(values.filterForm.filter_tree, pathKeys, (node) => ({
                type: 'not' as const,
                child: node,
            }))
            actions.setFilterFormValue('filter_tree', newTree)
        },
        unwrapNot: ({ pathKeys }) => {
            const newTree = updateAtPath(values.filterForm.filter_tree, pathKeys, (node) => {
                if (node.type === 'not') {
                    return node.child
                }
                return node
            })
            actions.setFilterFormValue('filter_tree', newTree)
        },
        addChild: ({ pathKeys }) => {
            const newTree = updateAtPath(values.filterForm.filter_tree, pathKeys, (node) => {
                if (node.type === 'and' || node.type === 'or') {
                    return {
                        ...node,
                        children: [
                            ...node.children,
                            {
                                type: 'condition' as const,
                                field: 'event_name' as const,
                                operator: 'exact' as const,
                                value: '',
                            },
                        ],
                    }
                }
                return node
            })
            actions.setFilterFormValue('filter_tree', newTree)
        },
        removeChild: ({ pathKeys, childIndex }) => {
            const newTree = updateAtPath(values.filterForm.filter_tree, pathKeys, (node) => {
                if (node.type === 'and' || node.type === 'or') {
                    return {
                        ...node,
                        children: node.children.filter((_, i) => i !== childIndex),
                    }
                }
                return node
            })
            actions.setFilterFormValue('filter_tree', newTree)
        },
        convertToGroup: ({ pathKeys, groupType }) => {
            const newTree = updateAtPath(values.filterForm.filter_tree, pathKeys, (node) => ({
                type: groupType,
                children: [node],
            }))
            actions.setFilterFormValue('filter_tree', newTree)
        },
        addTestCase: () => {
            const newCases = [
                ...values.filterForm.test_cases,
                { _key: nextTestCaseKey(), event_name: '', distinct_id: '', expected_result: 'drop' as const },
            ]
            actions.setFilterFormValue('test_cases', newCases)
        },
        removeTestCase: ({ index }) => {
            actions.setFilterFormValue(
                'test_cases',
                values.filterForm.test_cases.filter((_, i) => i !== index)
            )
        },
        updateTestCase: ({ index, updates }) => {
            const newCases = values.filterForm.test_cases.map((tc, i) => (i === index ? { ...tc, ...updates } : tc))
            actions.setFilterFormValue('test_cases', newCases)
        },
    })),

    // Load existing config from the API on mount
    afterMount(({ actions, values }) => {
        const { currentTeamId } = values
        api.get(`api/environments/${currentTeamId}/event_filter/`)
            .then((data) => {
                if (!data) {
                    return
                }
                actions.setFilterFormValue('id', data.id)
                actions.setFilterFormValue('mode', data.mode ?? 'disabled')
                if (data.filter_tree?.type) {
                    actions.setFilterFormValue('filter_tree', normalizeRootToGroup(data.filter_tree))
                }
                const testCases = (data.test_cases ?? []).map((tc: Omit<TestCase, '_key'>) => ({
                    ...tc,
                    _key: nextTestCaseKey(),
                }))
                actions.setFilterFormValue('test_cases', testCases)
            })
            .catch((error) => {
                lemonToast.error(`Failed to load event filter config: ${error.message ?? error}`)
            })
    }),
])
