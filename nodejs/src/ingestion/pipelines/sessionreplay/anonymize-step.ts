import { drop, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

import { anonymizeParsedMessage } from './anonymize/anonymize-event'
import { ScrubContext } from './anonymize/config'
import { ParsedMessageData } from './kafka/types'

export interface AnonymizeStepInput {
    parsedMessage: ParsedMessageData
}

export interface AnonymizeStepConfig {
    /** Shared, immutable scrub context (allow lists + tunables). */
    scrubContext: ScrubContext
}

/**
 * Anonymizes the parsed events in place before recording. Drops the message if any
 * event can't be anonymized — fail-closed, since blocks are written unencrypted.
 */
export function createAnonymizeStep<T extends AnonymizeStepInput>(config: AnonymizeStepConfig): ProcessingStep<T, T> {
    const { scrubContext } = config

    return async function anonymizeStep(input) {
        const { failed } = await anonymizeParsedMessage(scrubContext, input.parsedMessage)
        if (failed) {
            return drop('anonymize_failed')
        }
        return ok(input)
    }
}
