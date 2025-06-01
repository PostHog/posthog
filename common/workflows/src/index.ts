///////////////////////////////////////////////////////////////////////////////
// Workflow
///////////////////////////////////////////////////////////////////////////////
export interface Workflow {
    id: string
    name: string
    description: string
    workflow: {
        nodes: WorkflowNode[]
        edges: WorkflowEdge[]
    }
    created_at: string | null
    updated_at: string | null
    created_by: {
        uuid: string
        id: number
    } | null
    version: number
}

///////////////////////////////////////////////////////////////////////////////
// Journey
///////////////////////////////////////////////////////////////////////////////

// A journey is an invocation of a workflow
export interface Journey extends Workflow {
    globals: JourneyGlobals
    state: {
        path: {
            node_id: string
            outgoing_edge_id: string | null
        }[]
        current_node_id: string
    }
}

// TODO: DRY this out with HogFunctionInvocationGlobals in frontend/src/types.ts and plugin-server/src/types.ts
type JourneyGlobals = {
    project: {
        id: number
        name: string
        url: string
    }
    source?: {
        name: string
        url: string
    }
    event: {
        uuid: string
        event: string
        elements_chain: string
        distinct_id: string
        properties: Record<string, any>
        timestamp: string
        url: string
    }
    person?: {
        id: string
        properties: Record<string, any>
        name: string
        url: string
    }
    groups?: Record<
        string,
        {
            id: string // the "key" of the group
            type: string
            index: number
            url: string
            properties: Record<string, any>
        }
    >
}

///////////////////////////////////////////////////////////////////////////////
// Nodes
///////////////////////////////////////////////////////////////////////////////
export type WorkflowNode = {
    id: string
    type: WorkflowNodeType
    data: WorkflowNodeData
}
export type WorkflowNodeType = 'trigger' | 'email' | 'condition' | 'delay' | 'delay_until' | 'exit'

export interface WorkflowNodeData extends Record<string, unknown> {
    label: string
    description: string
    config: WorkflowNodeConfig | null
}
export interface WorkflowNodeConfig {
    input_schema: WorkflowNodeInputSchemaType[]
    inputs: Record<string, unknown>
}

export interface TriggerNodeConfig extends WorkflowNodeConfig {
    filters: WorkflowFilter[]
}

export interface MessageNodeConfig extends WorkflowNodeConfig {
    type: 'email'
    content: {
        email: {
            from: string
            html: string
            text: string
            design: Record<string, unknown>
            subject: string
        }
    }
    success_edge_id: string
    failure_edge_id: string
}

export interface DecisionNodeConfig extends WorkflowNodeConfig {
    conditions: {
        filters: WorkflowFilter[]
        /**
         * Id of the edge that this condition is connected to.
         * If the condition passes, the edge connected to this handle
         * will be used to traverse to the next node.
         */
        condition_edge_id: string
    }[]
}

export interface DelayNodeConfig extends WorkflowNodeConfig {
    delay_minutes: number
    /** Id of the edge to be traveled down after the delay. */
    delay_edge_id: string
}

///////////////////////////////////////////////////////////////////////////////
// Edges
///////////////////////////////////////////////////////////////////////////////
export type WorkflowEdge = {
    /** Unique id of an edge. */
    id: string
    /** Type of edge defined in `edgeTypes`. */
    type?: 'default'
    /** Id of source node. */
    source: string
    /** Id of target node. */
    target: string
    /** Id of source handle, only needed if there are multiple handles per node. */
    sourceHandle?: string | null
    /** Id of target handle, only needed if there are multiple handles per node. */
    targetHandle?: string | null
    data?: WorkflowEdgeData
}
export interface WorkflowEdgeData extends Record<string, unknown> {
    label?: string
}

///////////////////////////////////////////////////////////////////////////////
// Common types
///////////////////////////////////////////////////////////////////////////////

// TODO: DRY these out with duplicate interfaces in frontend/src/types.ts and plugin-server/src/types.ts
export type PropertyFilterBaseValue = string | number | bigint
export type PropertyFilterValue = PropertyFilterBaseValue | PropertyFilterBaseValue[] | null

export enum PropertyFilterType {
    /** Event metadata and fields on the clickhouse events table */
    Meta = 'meta',
    /** Event properties */
    Event = 'event',
    EventMetadata = 'event_metadata',
    /** Person properties */
    Person = 'person',
    Element = 'element',
    /** Event property with "$feature/" prepended */
    Feature = 'feature',
    Session = 'session',
    Cohort = 'cohort',
    Recording = 'recording',
    LogEntry = 'log_entry',
    Group = 'group',
    HogQL = 'hogql',
    DataWarehouse = 'data_warehouse',
    DataWarehousePersonProperty = 'data_warehouse_person_property',
    ErrorTrackingIssue = 'error_tracking_issue',
    ErrorTrackingIssueProperty = 'error_tracking_issue_property',
}

interface BasePropertyFilter {
    key: string
    value?: PropertyFilterValue
    label?: string
    type?: PropertyFilterType
}

export enum PropertyOperator {
    Exact = 'exact',
    IsNot = 'is_not',
    IContains = 'icontains',
    NotIContains = 'not_icontains',
    Regex = 'regex',
    NotRegex = 'not_regex',
    GreaterThan = 'gt',
    GreaterThanOrEqual = 'gte',
    LessThan = 'lt',
    LessThanOrEqual = 'lte',
    IsSet = 'is_set',
    IsNotSet = 'is_not_set',
    IsDateExact = 'is_date_exact',
    IsDateBefore = 'is_date_before',
    IsDateAfter = 'is_date_after',
    Between = 'between',
    NotBetween = 'not_between',
    Minimum = 'min',
    Maximum = 'max',
    In = 'in',
    NotIn = 'not_in',
    IsCleanedPathExact = 'is_cleaned_path_exact',
}

interface EventPropertyFilter extends BasePropertyFilter {
    type: PropertyFilterType.Event
    operator: PropertyOperator
}

interface EventMetadataPropertyFilter extends BasePropertyFilter {
    type: PropertyFilterType.EventMetadata
    operator: PropertyOperator
}

interface PersonPropertyFilter extends BasePropertyFilter {
    type: PropertyFilterType.Person
    operator: PropertyOperator
}

export type WorkflowFilter = EventPropertyFilter | EventMetadataPropertyFilter | PersonPropertyFilter

// TODO: DRY this out with duplicate HogFunctionInputSchemaType in frontend/src/types.ts
export type WorkflowNodeInputSchemaType = {
    type: 'string' | 'boolean' | 'dictionary' | 'choice' | 'json' | 'integration' | 'integration_field' | 'email'
    key: string
    label: string
    choices?: { value: string; label: string }[]
    required?: boolean
    default?: any
    secret?: boolean
    hidden?: boolean
    templating?: boolean
    description?: string
    integration?: string
    integration_key?: string
    integration_field?: string
    requires_field?: string
    requiredScopes?: string
}
