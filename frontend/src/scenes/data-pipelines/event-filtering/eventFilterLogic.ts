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

// Tree node types
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
    event_name: string
    distinct_id: string
    expected_result: 'drop' | 'ingest'
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

/** Evaluate a filter tree against a test event. Returns true if the event should be dropped. */
export function evaluateFilterTree(node: FilterNode, event: Record<string, string>): boolean {
    switch (node.type) {
        case 'condition': {
            const fieldValue = event[node.field]
            if (fieldValue === undefined || fieldValue === '') {
                return false
            }
            switch (node.operator) {
                case 'exact':
                    return fieldValue === node.value
                case 'contains':
                    return fieldValue.includes(node.value)
            }
            return false
        }
        case 'and':
            return node.children.length > 0 && node.children.every((child) => evaluateFilterTree(child, event))
        case 'or':
            return node.children.some((child) => evaluateFilterTree(child, event))
        case 'not':
            return !evaluateFilterTree(node.child, event)
    }
}

/** Check if a filter tree contains at least one condition leaf */
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

/** Check that all condition leaves have non-empty values */
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

function updateAtPath(node: any, pathKeys: (string | number)[], updater: (node: FilterNode) => FilterNode): any {
    if (pathKeys.length === 0) {
        return updater(node)
    }
    const [head, ...rest] = pathKeys
    if (Array.isArray(node)) {
        const copy = [...node]
        copy[head as number] = updateAtPath(copy[head as number], rest, updater)
        return copy
    }
    const copy = { ...node }
    copy[head] = updateAtPath(copy[head], rest, updater)
    return copy
}

export const eventFilterLogic = kea<eventFilterLogicType>([
    path(['scenes', 'data-pipelines', 'event-filtering', 'eventFilterLogic']),
    actions({
        updateTreeNode: (pathKeys: (string | number)[], node: FilterNode) => ({ pathKeys, node }),
        wrapInNot: (pathKeys: (string | number)[]) => ({ pathKeys }),
        unwrapNot: (pathKeys: (string | number)[]) => ({ pathKeys }),
        addChild: (pathKeys: (string | number)[]) => ({ pathKeys }),
        removeChild: (pathKeys: (string | number)[], childIndex: number) => ({ pathKeys, childIndex }),
        convertToGroup: (pathKeys: (string | number)[], groupType: 'and' | 'or') => ({ pathKeys, groupType }),
        addTestCase: true,
        removeTestCase: (index: number) => ({ index }),
        updateTestCase: (index: number, updates: Partial<TestCase>) => ({ index, updates }),
    }),
    forms(({ values }) => ({
        filterForm: {
            defaults: DEFAULT_FORM,
            errors: ({ filter_tree, mode }: EventFilterFormValues) => ({
                filter_tree: (() => {
                    if (mode !== 'disabled' && !treeHasConditions(filter_tree)) {
                        return 'Filter must have at least one condition to be activated'
                    }
                    if (treeHasConditions(filter_tree) && treeHasEmptyValues(filter_tree)) {
                        return 'All conditions must have a value'
                    }
                    return undefined
                })(),
            }),
            submit: async (formValues) => {
                const { currentTeamId } = values

                // Force-disable if tests are failing
                if (formValues.mode === 'live' && !values.allTestsPass && formValues.test_cases.length > 0) {
                    formValues = { ...formValues, mode: 'dry_run' }
                }

                await api.create(`api/environments/${currentTeamId}/event_filter/`, formValues)
                lemonToast.success('Event filter saved')
            },
        },
    })),
    selectors({
        currentTeamId: [() => [teamLogic.selectors.currentTeamId], (id: number) => id],
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
                    name: 'Event filtering',
                    iconType: 'data_pipeline',
                },
            ],
        ],
    }),
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
                { event_name: '', distinct_id: '', expected_result: 'drop' as const },
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
    afterMount(({ actions, values }) => {
        const { currentTeamId } = values
        api.get(`api/environments/${currentTeamId}/event_filter/`).then((data) => {
            actions.setFilterFormValue('id', data.id)
            actions.setFilterFormValue('mode', data.mode ?? 'disabled')
            if (data.filter_tree?.type) {
                actions.setFilterFormValue('filter_tree', data.filter_tree)
            }
            actions.setFilterFormValue('test_cases', data.test_cases ?? [])
        })
    }),
])
