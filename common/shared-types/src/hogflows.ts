export type HogFlow = {
    // Primary key is id + version
    id: string
    team_id: number
    version: number
    status: 'active' | 'draft' | 'archived'

    trigger:
        | {
              type: 'event'
              filters: any // HogFunctionFilters
          }
        | {
              type: 'pre-processed-event'
              filters: any // HogFunctionFilters
          }
        | {
              type: 'schedule'
              cron: string
          }
        | {
              type: 'webhook'
              hog_function_id: string
          }

    trigger_masking: {
        ttl: number
        hash: string
        // bytecode: HogBytecode
        threshold: number
    }

    conversion: {
        window: number
        // cohort_id: number
        filters: any // HogFunctionFilters
    }
    exit_condition:
        | 'exit_on_conversion'
        | 'exit_on_trigger_not_matched'
        | 'exit_on_trigger_not_matched_or_conversion'
        | 'exit_only_at_end'

    // workflow graph
    edges: {
        from: string
        to: string
        type: 'continue' | 'branch'
        index: number
    }[]

    actions: {
        id: string
        name: string
        description: string
        type: 'exit_action' | 'conditional_branch' | 'delay' | 'wait_for_condition' | 'message' | 'hog_function'
        config: any // HogFunctionInputSchemaType[] // Try to type this strongly to the "type"

        // Maybe v1?
        on_error: 'continue' | 'abort' | 'complete' | 'branch'

        created: number
        updated: Date
        position: number
    }[]

    abort_action?: string
}

export type HogFlowInvocation = {
    id: string
    team_id: number
    hog_flow_id: string
    hog_flow_version: number
    variables: HogFlowInvocationVariables
    state?: {
        current_action_id: string
    }

    // Job queue specific values
    queue: 'hogflow' | 'fetch' | 'hog' | 'email'
    queueParameters?: any // dependent on queue type
    queuePriority?: number
    queueScheduledAt?: Date
    queueMetadata?: Record<string, any> | null //
    queueSource?: 'postgres' | 'kafka'
}

export type HogFlowInvocationResult = {
    invocation: HogFlowInvocation
    result: {
        next_action_id: string
        error?: string
        variables?: Record<string, any>
        metrics: any
        logs: any
    }
}

export type HogFlowInvocationVariables = {
    event: {
        distinct_id: string
        properties: Record<string, any>
    }
    person: {
        distinct_id: string
        properties: Record<string, any>
    }
}
