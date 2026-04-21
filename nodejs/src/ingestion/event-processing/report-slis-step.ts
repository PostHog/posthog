import { Message } from 'node-rdkafka'

import { EventHeaders } from '../../types'
import { ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'
import { IndicatorHandle } from '../slas/types'

export interface ReportSlisStepInput {
    headers: EventHeaders
    message: Message
}

/**
 * Observes ingestion SLIs for the current event. Runs after the emit step,
 * so the measurement includes any synchronous work done during emit.
 *
 * Kept separate from the emit step so SLI reporting is explicit in the
 * pipeline definition and independently testable. Terminates in `void` — it
 * is intended to be the final step of an event subpipeline. The step is a
 * no-op if the `now` header or partition is missing.
 */
export function createReportSlisStep<T extends ReportSlisStepInput>(
    lagObserver: IndicatorHandle
): ProcessingStep<T, void> {
    return function reportSlisStep(input) {
        const { headers, message } = input
        if (headers?.now && message?.partition !== undefined) {
            const lag = Date.now() - headers.now.getTime()
            lagObserver.observe(lag)
        }
        return Promise.resolve(ok(undefined))
    }
}
