export type HogFlow = {
    id: string
    team_id: number
    version: number

    name: string
    status: 'active' | 'draft' | 'archived'

    trigger: {
        type: 'event'
        // TODO(team-messaging): use HogFunctionFilters instead of any
        filters: any
    }
    // | {
    //       type: 'pre-processed-event'
    //       // TODO(team-messaging): use HogFunctionFilters instead of any
    //       filters: any
    //   }
    // | {
    //       type: 'schedule'
    //       cron: string
    //   }
    // | {
    //       type: 'webhook'
    //       hog_function_id: string
    //   }

    trigger_masking: {
        ttl: number
        hash: string
        // bytecode: HogBytecode
        threshold: number
    }

    conversion: {
        window_minutes: number
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
        // TODO(team-messaging): use HogFunctionInputSchemaType[] instead of any
        config: any

        // Maybe v1?
        on_error: 'continue' | 'abort' | 'complete' | 'branch'

        created_at: number
        updated_at: number
        position: number
    }[]

    abort_action?: string
}
