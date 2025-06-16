import { randomUUID } from 'crypto'

import { HogFlow, HogFlowAction } from '~/src/schema/hogflow'
import { insertRow } from '~/tests/helpers/sql'

import { Team } from '../../types'
import { PostgresRouter } from '../../utils/db/postgres'
import { UUIDT } from '../../utils/utils'
import { CyclotronJobInvocationHogFlow, HogFlowInvocationContext } from '../types'

export const createHogFlow = (hogFlow: Partial<HogFlow>) => {
    const item: HogFlow = {
        id: randomUUID(),
        version: 1,
        name: 'Hog Flow',
        team_id: 1,
        status: 'active',
        trigger: {
            type: 'event',
            filters: {},
        },
        exit_condition: 'exit_on_conversion',
        edges: [],
        actions: [],
        ...hogFlow,
    }

    return item
}

export const createHogFlowAction = <T extends HogFlowAction['type']>(
    type: T,
    config: Extract<HogFlowAction, { type: T }>['config']
): Extract<HogFlowAction, { type: T }> => {
    return {
        id: randomUUID(),
        name: 'Action',
        description: 'Test action',
        on_error: 'continue',
        created_at: new Date().getTime(),
        updated_at: new Date().getTime(),
        type,
        config,
    } as Extract<HogFlowAction, { type: T }>
}

export const insertHogFlow = async (
    postgres: PostgresRouter,
    team_id: Team['id'],
    hogFlow: Partial<HogFlow> = {}
): Promise<HogFlow> => {
    // This is only used for testing so we need to override some values

    const res = await insertRow(postgres, 'posthog_hogflow', {
        ...createHogFlow({
            ...hogFlow,
            team_id: team_id,
        }),
        description: '',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        created_by_id: 1001,
    })
    return res
}

export const createHogFlowInvocationContext = (
    data: Partial<HogFlowInvocationContext> = {}
): HogFlowInvocationContext => {
    return {
        ...data,
    }
}

export const createExampleHogFlowInvocation = (
    _hogFlow: Partial<HogFlow> = {},
    _context: Partial<HogFlowInvocationContext> = {}
): CyclotronJobInvocationHogFlow => {
    const hogFlow = createHogFlow(_hogFlow)
    // Add the source of the trigger to the globals

    const context = createHogFlowInvocationContext(_context)

    return {
        id: new UUIDT().toString(),
        state: {
            ...context,
        },
        teamId: hogFlow.team_id,
        functionId: hogFlow.id,
        hogFlow,
        queue: 'hog',
        queuePriority: 0,
    }
}
