import { HogFunctionInvocationAsyncResponse, HogFunctionInvocationResult, HogFunctionType } from './types'

export type HogWatcherObservation = {
    rating: number
    successes: number
    failures: number
    asyncFunctionFailures: number
    asyncFunctionSuccesses: number
}

/**
 * HogWatcher is responsible for observing metrics of running hog functions, including their async calls.
 * It build a rating for each function and decides whether that function is _hogging_ resources.
 * If so, it marks it as such and then can be used to control the flow of the function.
 */
export class HogWatcher {
    // TODO: Move to redis or some other shared storage
    observations: Record<HogFunctionType['id'], HogWatcherObservation> = {}

    constructor() {}

    private patchObservation(id: HogFunctionType['id'], update: (x: HogWatcherObservation) => HogWatcherObservation) {
        const observation: HogWatcherObservation = (this.observations[id] = this.observations[id] ?? {
            successes: 0,
            failures: 0,
            asyncFunctionFailures: 0,
            asyncFunctionSuccesses: 0,
            rating: 0,
        })

        this.observations[id] = update(observation)
        this.observations[id].rating = this.calculateRating(this.observations[id])
        console.log('Observation updated', id, this.observations[id])
    }

    private calculateRating(observation: HogWatcherObservation): number {
        // Rating is from 0 to 1
        // 1 - Function is working perfectly
        // 0 - Function is not working at all

        const totalInvocations = observation.successes + observation.failures
        const totalAsyncInvocations = observation.asyncFunctionSuccesses + observation.asyncFunctionFailures

        const successRate = totalInvocations ? observation.successes / totalInvocations : 1
        const asyncSuccessRate = totalAsyncInvocations ? observation.asyncFunctionSuccesses / totalAsyncInvocations : 1

        return Math.min(1, successRate, asyncSuccessRate)
    }

    observeResults(results: HogFunctionInvocationResult[]) {
        // TODO: Actually measure something and store the result
        results.forEach((result) => {
            this.patchObservation(result.hogFunctionId, (x) => ({
                ...x,
                successes: x.successes + (result.finished ? 1 : 0),
                failures: x.failures + (result.error ? 1 : 0),
            }))
        })
    }

    observeAsyncFunctionResponses(responses: HogFunctionInvocationAsyncResponse[]) {
        // NOTE: This probably wants to be done using the response status instead :thinking:
        responses.forEach((response) => {
            this.patchObservation(response.hogFunctionId, (x) => ({
                ...x,
                asyncFunctionSuccesses: x.asyncFunctionSuccesses + (response.error ? 0 : 1),
                asyncFunctionFailures: x.asyncFunctionFailures + (response.error ? 1 : 0),
            }))
        })
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
