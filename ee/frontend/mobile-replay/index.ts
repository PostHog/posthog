import { eventWithTime } from '@rrweb/types'
import Ajv, { ErrorObject } from 'ajv'

import { mobileEventWithTime } from './mobile.types'
import mobileSchema from './schema/mobile/rr-mobile-schema.json'
import webSchema from './schema/web/rr-web-schema.json'
import { makeFullEvent, makeMetaEvent } from './transformers'

const ajv = new Ajv({
    allowUnionTypes: true,
}) // options can be passed, e.g. {allErrors: true}

const transformers: Record<number, (x: any) => eventWithTime> = {
    4: makeMetaEvent,
    10: makeFullEvent,
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

export function transformEventToWeb(event: unknown): eventWithTime | null {
    if (!couldBeEventWithTime(event)) {
        console.warn(`No type in event: ${JSON.stringify(event)}`)
        return null
    }

    const transformer = transformers[event.type]
    if (transformer) {
        const transformed = transformer(event)
        validateAgainstWebSchema(transformed)
        return transformed
    } else {
        console.warn(`No transformer for event type ${event.type}`)
        return event as eventWithTime
    }
}

export function transformToWeb(mobileData: (eventWithTime | mobileEventWithTime)[]): eventWithTime[] {
    return mobileData.reduce((acc, event) => {
        const transformed = transformEventToWeb(event)
        if (transformed) {
            acc.push(transformed)
        }
        return acc
    }, [] as eventWithTime[])
}

export function validateAgainstWebSchema(data: unknown): boolean {
    const validationResult = webSchemaValidator(data)
    if (!validationResult) {
        console.error(webSchemaValidator.errors)
    }
    // we are passing all data through this validation now and don't know how safe the schema is
    // TODO would we ever want to reject here?
    return true
}
