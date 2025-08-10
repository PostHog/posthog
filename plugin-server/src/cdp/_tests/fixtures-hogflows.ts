import { HogFlow } from '~/schema/hogflow'
import { insertRow } from '~/tests/helpers/sql'

import { PostgresRouter } from '../../utils/db/postgres'
import { UUIDT } from '../../utils/utils'
import { CyclotronJobInvocationHogFlow, CyclotronPerson, HogFlowInvocationContext } from '../types'
import { convertToHogFunctionFilterGlobal } from '../utils/hog-function-filtering'
import { createHogExecutionGlobals } from './fixtures'

export const insertHogFlow = async (postgres: PostgresRouter, hogFlow: HogFlow): Promise<HogFlow> => {
    // This is only used for testing so we need to override some values

    const res = await insertRow(postgres, 'posthog_hogflow', {
        ...hogFlow,
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
        actionStepCount: 0,
        ...data,
    }
}

export const createExampleHogFlowInvocation = (
    hogFlow: HogFlow,
    _context: Partial<HogFlowInvocationContext> = {},
    _person: CyclotronPerson | undefined = undefined
): CyclotronJobInvocationHogFlow => {
    // Add the source of the trigger to the globals

    const context = createHogFlowInvocationContext(_context)

    const person: CyclotronPerson = {
        id: 'person_id',
        properties: {
            name: 'John Doe',
        },
        name: '',
        url: '',
        ..._person,
    }

    return {
        id: new UUIDT().toString(),
        state: {
            ...context,
        },
        teamId: hogFlow.team_id,
        functionId: hogFlow.id,
        hogFlow,
        person,
        filterGlobals: convertToHogFunctionFilterGlobal({
            event: context.event,
            person,
            groups: {},
        }),
        queue: 'hogflow',
        queuePriority: 0,
    }
}
