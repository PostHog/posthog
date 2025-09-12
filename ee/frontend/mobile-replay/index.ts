import Ajv, { ErrorObject } from 'ajv'
import posthog from 'posthog-js'

import { eventWithTime } from '@posthog/rrweb-types'

import { mobileEventWithTime } from './mobile.types'
import mobileSchema from './schema/mobile/rr-mobile-schema.json'
import webSchema from './schema/web/rr-web-schema.json'
import { makeCustomEvent, makeFullEvent, makeIncrementalEvent, makeMetaEvent } from './transformer/transformers'

const ajv = new Ajv({
    allowUnionTypes: true,
}) // options can be passed, e.g. {allErrors: true}

const transformers: Record<number, (x: any) => eventWithTime> = {
    2: makeFullEvent,
    3: makeIncrementalEvent,
    4: makeMetaEvent,
    5: makeCustomEvent,
}

const mobileSchemaValidator = ajv.compile(mobileSchema)

export function validateFromMobile(data: unknown): {
    isValid: boolean
    errors: ErrorObject[] | null | undefined
} {
    const isValid = mobileSchemaValidator(data)
    return {
        isValid,
        errors: isValid ? null : mobileSchemaValidator.errors,
    }
}

const webSchemaValidator = ajv.compile(webSchema)

function couldBeEventWithTime(x: unknown): x is eventWithTime | mobileEventWithTime {
    return typeof x === 'object' && x !== null && 'type' in x && 'timestamp' in x
}

export function transformEventToWeb(event: unknown, validateTransformation?: boolean): eventWithTime {
    // the transformation needs to never break a recording itself
    // so, we default to returning what we received
    // replacing it only if there's a valid transformation
    let result = event as eventWithTime
    try {
        if (couldBeEventWithTime(event)) {
            const transformer = transformers[event.type]
            if (transformer) {
                const transformed = transformer(event)
                if (validateTransformation) {
                    validateAgainstWebSchema(transformed)
                }
                result = transformed
            }
        }
    } catch (e) {
        posthog.captureException(e, { event })
    }
    return result
}

export function transformToWeb(mobileData: (eventWithTime | mobileEventWithTime)[]): eventWithTime[] {
    return mobileData.reduce((acc, event) => {
        const transformed = transformEventToWeb(event)
        acc.push(transformed ? transformed : (event as eventWithTime))
        return acc
    }, [] as eventWithTime[])
}

export function validateAgainstWebSchema(data: unknown): boolean {
    return webSchemaValidator(data)
}
