import { randomUUID } from 'crypto'

import { HogFlow, HogFlowAction } from '~/schema/hogflow'
import { insertRow } from '~/tests/helpers/sql'

import { Team } from '../../types'
import { PostgresRouter } from '../../utils/db/postgres'
import { UUIDT } from '../../utils/utils'
import { CyclotronJobInvocationHogFlow, HogFlowInvocationContext } from '../types'
import { createHogExecutionGlobals } from './fixtures'

export const createHogFlowAction = <T extends HogFlowAction['type']>(
    overrides: Pick<Extract<HogFlowAction, { type: T }>, 'type' | 'config'> &
        Partial<Omit<Extract<HogFlowAction, { type: T }>, 'type' | 'config'>>
): Extract<HogFlowAction, { type: T }> => {
    const action = {
        id: randomUUID(),
        name: 'Action',
        description: 'Test action',
        on_error: 'continue',
        created_at: new Date().getTime(),
        updated_at: new Date().getTime(),
        ...overrides,
    } as unknown as Extract<HogFlowAction, { type: T }>
    // NOTE(bw): The type cast here is nasty but the getting the type inference correct is beyond me right now!

    return action
}

export const insertHogFlow = async (
    postgres: PostgresRouter,
    team_id: Team['id'],
    hogFlow: HogFlow
): Promise<HogFlow> => {
    // This is only used for testing so we need to override some values

    const res = await insertRow(postgres, 'posthog_hogflow', {
        ...{
            ...hogFlow,
            team_id: team_id,
        },
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
        event: {
            ...createHogExecutionGlobals().event,
            ...data.event,
        },
        ...data,
    }
}

export const createExampleHogFlowInvocation = (
    hogFlow: HogFlow,
    _context: Partial<HogFlowInvocationContext> = {}
): CyclotronJobInvocationHogFlow => {
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
