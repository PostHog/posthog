import { UUIDT } from '~/utils/utils'

import { CyclotronJobInvocationHogFunction, HogFunctionType } from '../types'
import { createHogFunction } from './fixtures'
import { SAMPLE_GLOBALS } from './fixtures'

export const createExampleNativeInvocation = (
    _hogFunction: Partial<HogFunctionType> = {},
    inputs: Record<string, any> = {}
): CyclotronJobInvocationHogFunction => {
    const hogFunction = createHogFunction(_hogFunction)

    return {
        id: new UUIDT().toString(),
        state: {
            globals: {
                inputs,
                ...SAMPLE_GLOBALS,
            },
            timings: [],
            attempts: 0,
        },
        teamId: hogFunction.team_id,
        functionId: hogFunction.id,
        hogFunction,
        queue: 'native',
        queuePriority: 0,
    }
}
