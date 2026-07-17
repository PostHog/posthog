import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { PluginEvent } from '~/plugin-scaffold'

export interface StripPersonUpdatePropertiesStepInput {
    normalizedEvent: PluginEvent
}

/**
 * Strips `$set` / `$set_once` from the normalized event for read-only pipelines
 * (e.g. AI). These pipelines never write the person, so createEvent merging
 * `$set` into person_properties (when processPerson is true) would put values on
 * the emitted event that were never persisted. Mutation is safe — the event is
 * consumed downstream.
 */
export function createStripPersonUpdatePropertiesStep<T extends StripPersonUpdatePropertiesStepInput>(): ProcessingStep<
    T,
    T
> {
    return function stripPersonUpdatePropertiesStep(input) {
        const properties = input.normalizedEvent.properties
        if (properties) {
            delete properties.$set
            delete properties.$set_once
        }
        return Promise.resolve(ok(input))
    }
}
