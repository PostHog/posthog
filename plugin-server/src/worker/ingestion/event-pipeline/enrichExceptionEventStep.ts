import { captureException } from '@sentry/node'
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

const COULD_NOT_PREPARE_FOR_FINGERPRINTING_COUNTER = new Counter({
    name: 'enrich_exception_events_could_not_prepare_for_fingerprinting',
    help: 'Counter for exceptions where the event could not be prepared for fingerprinting',
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

    let type: string | null = null
    let message: string | null = null
    let firstFunction: string | null = null
    let exceptionStack: string | null = null
    let exceptionList: any[] | null = null

    try {
        exceptionStack = event.properties['$exception_stack_trace_raw']
        exceptionList = event.properties['$exception_list']
        const fingerPrint = event.properties['$exception_fingerprint']
        type = event.properties['$exception_type']
        message = event.properties['$exception_message']

        if (fingerPrint) {
            EXTERNAL_FINGERPRINT_COUNTER.inc()
            return Promise.resolve(event)
        }
    } catch (e) {
        captureException(e)
        COULD_NOT_PREPARE_FOR_FINGERPRINTING_COUNTER.inc()
    }

    try {
        if (exceptionStack) {
            const parsedStack = JSON.parse(exceptionStack)
            if (parsedStack.length > 0) {
                firstFunction = parsedStack[0].function
            }
        } else if (exceptionList && exceptionList.length > 0) {
            const firstException = exceptionList[0]
            if (firstException.stacktrace) {
                // TODO: Should this be the last function instead?, or first in app function?
                firstFunction = firstException.stacktrace.frames[0].function
            }
        }
    } catch (e) {
        captureException(e)
        COULD_NOT_PARSE_STACK_TRACE_COUNTER.inc()
    }

    const fingerprint = [type, message, firstFunction].filter(Boolean)
    event.properties['$exception_fingerprint'] = fingerprint.length ? fingerprint : undefined

    if (event.properties['$exception_fingerprint']) {
        EXCEPTIONS_ENRICHED_COUNTER.inc()
    }

    return Promise.resolve(event)
}
