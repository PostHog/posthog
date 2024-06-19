import { HogFunctionInvocationAsyncResponse, HogFunctionInvocationResult, HogFunctionType } from './types'

export type HogWatcherObservation = {
    hogFunctionId: HogFunctionType['id']
    averageHogDurationMs: number
    averageAsyncFunctionDurationMs: number
    rating: number
}

/**
 * HogWatcher is responsible for observing metrics of running hog functions, including their async calls.
 * It build a rating for each function and decides whether that function is _hogging_ resources.
 * If so, it marks it as such and then can be used to control the flow of the function.
 */
export class HogWatcher {
    // TODO: Move to redis or some other shared storage
    observations: Record<HogFunctionType['id'], any> = {}

    constructor() {}

    observeResult(result: HogFunctionInvocationResult) {
        console.log('HogWatcher: observe', result)
    }

    async observeResults(results: HogFunctionInvocationResult[]) {
        // TODO: Actually measure something and store the result
        results.forEach((result) => {
            this.observeResult(result)
        })
    }

    async observeAsyncFunctionResponses(responses: HogFunctionInvocationAsyncResponse[]) {
        // TODO
    }

    getOverflowedHogFunctionIds(): HogFunctionType['id'][] {
        // TODO
        return []
    }

    isHogFunctionOverflowed(hogFunctionId: HogFunctionType['id']): boolean {
        return this.getOverflowedHogFunctionIds().includes(hogFunctionId)
    }

    getDisabledHogFunctionIds(): HogFunctionType['id'][] {
        // TODO
        return []
    }

    isHogFunctionDisabled(hogFunctionId: HogFunctionType['id']): boolean {
        return this.getDisabledHogFunctionIds().includes(hogFunctionId)
    }
}
