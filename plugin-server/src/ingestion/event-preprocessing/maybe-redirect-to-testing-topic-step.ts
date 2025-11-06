import { Message } from 'node-rdkafka'

import { ok, redirect } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export function createMaybeRedirectToTestingTopicStep<T extends { message: Message }>(
    testingTopic: string | null
): ProcessingStep<T, T> {
    return async function maybeRedirectToTestingTopicStep(input) {
        if (!testingTopic) {
            return ok(input)
        }
        return Promise.resolve(redirect('testing_topic', testingTopic))
    }
}
