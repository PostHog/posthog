import { Counter } from 'prom-client'

import { PreIngestionEvent } from '../../../types'
import { EventPipelineRunner } from './runner'

const EXTERNAL_FINGERPRINT_COUNTER = new Counter({
    name: 'enrich_exception_events_external_fingerprint',
    help: 'Counter for exceptions that already have a fingerprint',
})

const COULD_NOT_PARSE_STACK_TRACE_COUNTER = new Counter({
    name: 'enrich_exception_events_could_not_parse_stack_trace',
    help: 'Counter for exceptions where the stack trace could not be parsed',
})

const EXCEPTIONS_ENRICHED_COUNTER = new Counter({
    name: 'enrich_exception_events_enriched',
    help: 'Counter for exceptions that have been enriched',
})

export function enrichExceptionEventStep(
    _runner: EventPipelineRunner,
    event: PreIngestionEvent
): Promise<PreIngestionEvent> {
    if (event.event !== '$exception') {
        return Promise.resolve(event)
    }

    const exceptionStack = event.properties['$exception_stack_trace_raw']
    const fingerPrint = event.properties['$exception_fingerprint']
    const type = event.properties['$exception_type']
    const message = event.properties['$exception_message']
    let firstFunction: string | null = null

    if (fingerPrint) {
        EXTERNAL_FINGERPRINT_COUNTER.inc()
        return Promise.resolve(event)
    }

    try {
        const parsedStack = JSON.parse(exceptionStack)
        if (parsedStack.length > 0) {
            firstFunction = parsedStack[0].function
        }
    } catch (e) {
        COULD_NOT_PARSE_STACK_TRACE_COUNTER.inc()
    }

    const fingerprint = [type, message, firstFunction].filter(Boolean)
    event.properties['$exception_fingerprint'] = fingerprint.length ? fingerprint : undefined

    EXCEPTIONS_ENRICHED_COUNTER.inc()
    return Promise.resolve(event)
}
