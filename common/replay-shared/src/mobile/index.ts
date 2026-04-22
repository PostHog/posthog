import { eventWithTime } from '@posthog/rrweb-types'

import { noOpTelemetry, ReplayTelemetry } from '../telemetry'
import { mobileEventWithTime } from './mobile.types'
import { makeCustomEvent, makeFullEvent, makeIncrementalEvent, makeMetaEvent } from './transformer/transformers'

function couldBeEventWithTime(x: unknown): x is eventWithTime | mobileEventWithTime {
    return typeof x === 'object' && x !== null && 'type' in x && 'timestamp' in x
}

export function transformEventToWeb(event: unknown, telemetry: ReplayTelemetry = noOpTelemetry): eventWithTime {
    // the transformation needs to never break a recording itself
    // so, we default to returning what we received
    // replacing it only if there's a valid transformation
    let result = event as eventWithTime
    try {
        if (couldBeEventWithTime(event)) {
            const transformers: Record<number, (x: any) => eventWithTime> = {
                2: makeFullEvent,
                3: makeIncrementalEvent,
                4: makeMetaEvent,
                5: (x: any) => makeCustomEvent(x, telemetry),
            }
            const transformer = transformers[event.type]
            if (transformer) {
                result = transformer(event)
            }
        }
    } catch (e) {
        telemetry.captureException(e as Error, { event })
    }
    return result
}

export function transformToWeb(
    mobileData: (eventWithTime | mobileEventWithTime)[],
    telemetry: ReplayTelemetry = noOpTelemetry
): eventWithTime[] {
    return mobileData.reduce((acc, event) => {
        const transformed = transformEventToWeb(event, telemetry)
        acc.push(transformed ? transformed : (event as eventWithTime))
        return acc
    }, [] as eventWithTime[])
}
