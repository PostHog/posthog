import { eventWithTime } from '@posthog/rrweb-types'

import { mobileEventWithTime } from './mobile.types'
import { makeCustomEvent, makeFullEvent, makeIncrementalEvent, makeMetaEvent } from './transformer/transformers'

const transformers: Record<number, (x: any) => eventWithTime> = {
    2: makeFullEvent,
    3: makeIncrementalEvent,
    4: makeMetaEvent,
    5: makeCustomEvent,
}

function couldBeEventWithTime(x: unknown): x is eventWithTime | mobileEventWithTime {
    return typeof x === 'object' && x !== null && 'type' in x && 'timestamp' in x
}

export function transformEventToWeb(event: unknown): eventWithTime {
    let result = event as eventWithTime
    if (couldBeEventWithTime(event)) {
        const transformer = transformers[event.type]
        if (transformer) {
            result = transformer(event)
        }
    }
    return result
}

export function transformToWeb(mobileData: (eventWithTime | mobileEventWithTime)[]): eventWithTime[] {
    return mobileData.reduce((acc, event) => {
        try {
            const transformed = transformEventToWeb(event)
            acc.push(transformed ? transformed : (event as eventWithTime))
        } catch {
            acc.push(event as eventWithTime)
        }
        return acc
    }, [] as eventWithTime[])
}
