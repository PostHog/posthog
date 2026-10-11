import type { Edge, Node } from '@xyflow/react'

import type { LemonTagType } from 'lib/lemon-ui/LemonTag'
import { objectsEqual } from 'lib/utils/objects'
import {
    type EventFilterMode,
    type FilterNode,
    evaluateFilterTree,
} from 'scenes/data-pipelines/event-filtering/eventFilterLogic'

import { CyclotronJobTestInvocationResult, HogFunctionType, LogEntry } from '~/types'

export type FlowStepKind =
    | 'capture'
    | 'event_filtering'
    | 'transformation'
    | 'add'
    | 'person_processing'
    | 'stored'
    | 'disabled_label'
    | 'disabled_transformation'

export type FlowStep = {
    id: string
    kind: FlowStepKind
    hogFunction?: HogFunctionType
    /** 1-based position among the transformations. Only set for transformation steps. */
    position?: number
}

export type TestEvent = {
    event: string
    uuid: string
    distinct_id: string
    timestamp: string
    properties: Record<string, any>
}

export type TestStepOutcome = 'changed' | 'unchanged' | 'skipped' | 'dropped' | 'error' | 'passed' | 'kept' | 'counted'

export type EventFilterConfig = {
    mode: EventFilterMode
    filter_tree: FilterNode | null
}

export type TestStepResult = {
    outcome: TestStepOutcome
    input: TestEvent
    output: TestEvent | null
    logs: LogEntry[]
    errors: string[]
}

export type FlowNodeData = {
    step: FlowStep
}

export type FlowNode = Node<FlowNodeData>

export const CAPTURE_STEP_ID = 'capture'
export const EVENT_FILTERING_STEP_ID = 'event_filtering'
export const ADD_STEP_ID = 'add'
export const PERSON_PROCESSING_STEP_ID = 'person_processing'
export const STORED_STEP_ID = 'stored'
export const DISABLED_LABEL_STEP_ID = 'disabled_label'

// Shared by the panel and the logic, so that both use the same configuration form instance.
export const CONFIGURATION_LOGIC_KEY = 'transformations-flow'

export const EVENT_FILTER_MODE_TAGS: Record<EventFilterMode, { label: string; type: LemonTagType }> = {
    live: { label: 'On', type: 'success' },
    dry_run: { label: 'Dry run', type: 'warning' },
    disabled: { label: 'Off', type: 'muted' },
}

export const FLOW_NODE_WIDTH = 288
export const FLOW_NODE_HEIGHT = 64
const FLOW_NODE_GAP = 40
const FLOW_COLUMN_GAP = 96

export function getStepText(step: FlowStep): { title: string; description: string } {
    switch (step.kind) {
        case 'capture':
            return { title: 'Capture', description: 'Events arrive from your SDKs and the API' }
        case 'event_filtering':
            return { title: 'Event filtering', description: 'Drops events that match your filter' }
        case 'person_processing':
            return { title: 'Person processing', description: 'Updates person and group properties' }
        case 'stored':
            return { title: 'Stored in PostHog', description: 'Ready for insights, replays and destinations' }
        case 'add':
            return { title: 'Add a transformation', description: 'Runs after the steps above' }
        case 'transformation':
            return {
                title: step.hogFunction?.name ?? 'Transformation',
                description: `Step ${step.position}${step.hogFunction?.description ? ` · ${step.hogFunction.description}` : ''}`,
            }
        case 'disabled_label':
            return { title: 'Disabled transformations', description: 'Events do not go through these' }
        case 'disabled_transformation':
            return { title: step.hogFunction?.name ?? 'Transformation', description: 'Disabled · Does not run' }
    }
}

/**
 * Orders transformations the same way the ingestion pipeline runs them: by execution_order,
 * with null values last and ties broken by creation date.
 * Keep in sync with sortHogFunctions in nodejs/src/cdp/services/managers/hog-function-manager.service.ts.
 */
export function sortByExecutionOrder(hogFunctions: HogFunctionType[]): HogFunctionType[] {
    return [...hogFunctions].sort((a, b) => {
        if (a.execution_order == null && b.execution_order == null) {
            return a.created_at.localeCompare(b.created_at)
        }
        if (a.execution_order == null) {
            return 1
        }
        if (b.execution_order == null) {
            return -1
        }
        if (a.execution_order !== b.execution_order) {
            return a.execution_order - b.execution_order
        }
        return a.created_at.localeCompare(b.created_at)
    })
}

export function buildFlowSteps(orderedTransformations: HogFunctionType[]): FlowStep[] {
    return [
        { id: CAPTURE_STEP_ID, kind: 'capture' },
        { id: EVENT_FILTERING_STEP_ID, kind: 'event_filtering' },
        ...orderedTransformations.map(
            (hogFunction, index): FlowStep => ({
                id: hogFunction.id,
                kind: 'transformation',
                hogFunction,
                position: index + 1,
            })
        ),
        { id: ADD_STEP_ID, kind: 'add' },
        { id: PERSON_PROCESSING_STEP_ID, kind: 'person_processing' },
        { id: STORED_STEP_ID, kind: 'stored' },
    ]
}

export function buildDisabledSteps(disabledTransformations: HogFunctionType[]): FlowStep[] {
    if (disabledTransformations.length === 0) {
        return []
    }
    return [
        { id: DISABLED_LABEL_STEP_ID, kind: 'disabled_label' },
        ...disabledTransformations.map(
            (hogFunction): FlowStep => ({ id: hogFunction.id, kind: 'disabled_transformation', hogFunction })
        ),
    ]
}

/**
 * The flow is one column, from capture at the top to storage at the bottom.
 * Disabled transformations go in a second column next to the transformations, with no edges,
 * because events never go through them.
 */
export function buildFlowGraph(steps: FlowStep[], disabledSteps: FlowStep[]): { nodes: FlowNode[]; edges: Edge[] } {
    const firstTransformationRow = steps.findIndex((step) => step.kind === 'transformation' || step.kind === 'add')
    const disabledNodes = disabledSteps.map(
        (step, index): FlowNode => ({
            id: step.id,
            type: 'flowStep',
            position: {
                x: FLOW_NODE_WIDTH + FLOW_COLUMN_GAP,
                y: (firstTransformationRow + index) * (FLOW_NODE_HEIGHT + FLOW_NODE_GAP),
            },
            data: { step },
            width: FLOW_NODE_WIDTH,
            height: FLOW_NODE_HEIGHT,
            draggable: false,
            connectable: false,
        })
    )
    const nodes = steps.map(
        (step, index): FlowNode => ({
            id: step.id,
            type: 'flowStep',
            position: { x: 0, y: index * (FLOW_NODE_HEIGHT + FLOW_NODE_GAP) },
            data: { step },
            width: FLOW_NODE_WIDTH,
            height: FLOW_NODE_HEIGHT,
            draggable: false,
            connectable: false,
        })
    )
    const edges = steps.slice(1).map(
        (step, index): Edge => ({
            id: `${steps[index].id}->${step.id}`,
            source: steps[index].id,
            target: step.id,
            type: 'smoothstep',
        })
    )
    return { nodes: [...nodes, ...disabledNodes], edges }
}

/**
 * Moves one transformation by `offset` places and returns the 1-based orders for the rearrange API.
 * Returns null when the move would leave the list.
 * The result includes every transformation, so that null or duplicate execution_order values
 * get a fixed, unique position after the save.
 */
export function moveTransformation(
    orderedTransformations: HogFunctionType[],
    id: string,
    offset: -1 | 1
): Record<string, number> | null {
    const from = orderedTransformations.findIndex((hogFunction) => hogFunction.id === id)
    const to = from + offset
    if (from === -1 || to < 0 || to >= orderedTransformations.length) {
        return null
    }
    const reordered = [...orderedTransformations]
    const [moved] = reordered.splice(from, 1)
    reordered.splice(to, 0, moved)
    return Object.fromEntries(reordered.map((hogFunction, index) => [hogFunction.id, index + 1]))
}

export function toTestEvent(raw: Record<string, any>): TestEvent {
    return {
        event: raw.event,
        uuid: raw.uuid,
        distinct_id: raw.distinct_id,
        timestamp: raw.timestamp,
        properties: raw.properties ?? {},
    }
}

export function getTestStepResult(input: TestEvent, response: CyclotronJobTestInvocationResult): TestStepResult {
    const base = { input, logs: response.logs ?? [], errors: response.errors ?? [] }
    // Ingestion skips a transformation that fails and sends the event on without its changes.
    if (response.status === 'error') {
        return { ...base, outcome: 'error', output: input }
    }
    if (!response.result) {
        return { ...base, outcome: 'dropped', output: null }
    }
    const output = toTestEvent(response.result)
    if (response.status === 'skipped') {
        return { ...base, outcome: 'skipped', output }
    }
    return { ...base, outcome: objectsEqual(input, output) ? 'unchanged' : 'changed', output }
}

/** Mirrors the ingestion event filter, which checks only the event name and the distinct ID. */
export function getEventFilterStepResult(input: TestEvent, eventFilter: EventFilterConfig | null): TestStepResult {
    const base = { input, logs: [], errors: [] }
    const matches =
        !!eventFilter &&
        eventFilter.mode !== 'disabled' &&
        !!eventFilter.filter_tree &&
        evaluateFilterTree(eventFilter.filter_tree, { event_name: input.event, distinct_id: input.distinct_id })
    if (!matches) {
        return { ...base, outcome: 'kept', output: input }
    }
    return eventFilter.mode === 'live'
        ? { ...base, outcome: 'dropped', output: null }
        : { ...base, outcome: 'counted', output: input }
}

export function exampleTestEvent(uuid: string, timestamp: string): TestEvent {
    return {
        event: '$pageview',
        uuid,
        distinct_id: 'example-user',
        timestamp,
        properties: {
            $current_url: 'https://example.com/pricing',
            $pathname: '/pricing',
            $browser: 'Chrome',
            $os: 'Mac OS X',
            // A MaxMind test address, so the GeoIP transformation has a result to show.
            $ip: '89.160.20.129',
        },
    }
}
