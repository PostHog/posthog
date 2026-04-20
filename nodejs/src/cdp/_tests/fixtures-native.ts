import { UUIDT } from '~/utils/utils'

import { CyclotronJobInvocationHogFunction, HogFunctionType } from '../types'
import { createHogFunction } from './fixtures'
import { SAMPLE_GLOBALS } from './fixtures'

export const createExampleNativeInvocation = (
    hogFunctionOverrides: Partial<HogFunctionType> = {},
    inputs: Record<string, any> = {}
): CyclotronJobInvocationHogFunction => {
    const hogFunction = createHogFunction(hogFunctionOverrides)

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
        queue: 'hog',
        queuePriority: 0,
    }
}
